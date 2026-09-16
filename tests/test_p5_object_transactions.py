"""P5 foundation: real PostgreSQL locks, HTTP commands and ordinary editors.

This is not a substitute for the final two-browser COLLAB matrix.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import io
import uuid
import time

import pytest

from backend import identity, store as s
from tests.test_p3_identity_acl import (admin, clients, clear_auth_rate_limits, register,
                                       add_team_member, add_production_member)
from tests.test_p3_r2_interleavings import wait_for_db_waiters


@pytest.fixture
def team(admin, clients):
    project = admin.post('/api/projects', json={'name': 'P5 isolated collaboration'}).json()
    pid, production = project['id'], project['production_id']
    with s.db() as c:
        workspace = c.execute('SELECT workspace_id FROM productions WHERE id=%s', (production,)).fetchone()['workspace_id']
    members = []
    for nickname, role in [('Editor A', 'editor'), ('Editor B', 'editor'), ('Viewer', 'viewer')]:
        client, user, _ = register(admin, clients, nickname=nickname)
        assert user['platform_role'] == 'user'
        add_team_member(admin, workspace, user['id'])
        add_production_member(admin, production, user['id'], role)
        members.append((client, user))
    return {'admin': admin, 'pid': pid, 'production': production, 'workspace': workspace,
            'a': members[0][0], 'aid': members[0][1]['id'],
            'b': members[1][0], 'bid': members[1][1]['id'], 'viewer': members[2][0]}


def url(team, row=None, action=''):
    return '/api/projects/' + team['pid'] + '/objects' + ('/' + row['id'] if row else '') + action


def create(team, client=None, kind='shot', **content):
    if kind == 'shot':
        key = 'shot-' + uuid.uuid4().hex
        content = {'shot': {'id': key, 'uid': key, 'description': 'v1', **content}, 'nodes': []}
    elif kind == 'timeline':
        content = {'timeline': {'version': 2, 'tracks': [], **content}}
        existing = next(row for row in team['admin'].get(url(team)).json() if row['kind'] == 'timeline')
        response = team['admin'].post(url(team, existing, '/assign'), json={**version(existing),
            'assignee_id': team['bid'] if client is team['b'] else team['aid']})
        assert response.status_code == 200, response.text
        return response.json()
    result = (client or team['a']).post(url(team), json={'kind': kind, 'content': content})
    assert result.status_code == 201, result.text
    return result.json()


def version(row):
    return {'expected_revision': row['revision'], 'assignment_epoch': row['assignment_epoch']}


def save(team, row, content=None, client=None, **extra):
    if content is None or 'description' in content:
        patch = content or {'description': 'v2'}
        if row['kind'] == 'shot':
            content = {**row['content'], 'shot': {**row['content']['shot'], **patch}}
        elif row['kind'] == 'timeline':
            content = {'timeline': {**row['content']['timeline'], 'metadata': patch}}
    return (client or team['a']).patch(url(team, row), json={**version(row), 'content': content, **extra})


def test_two_editors_independent_objects_and_no_management_bypass(team):
    a = create(team)
    b = create(team, team['b'])
    assert a['assignee_id'] == team['aid'] and b['assignee_id'] == team['bid']
    assert save(team, a).status_code == 200
    assert save(team, b, client=team['b']).status_code == 200
    assert save(team, b, client=team['a']).status_code == 403
    assert save(team, a, client=team['admin']).status_code == 403
    assert save(team, a, client=team['viewer']).status_code == 403
    assert team['viewer'].post(url(team), json={'kind': 'shot', 'content': {}}).status_code == 403
    for row in (a, b):
        result = team['viewer'].get(url(team, row)).json()
        assert result['content']['shot']['description'] == 'v2' and result['revision'] == 2


def test_same_revision_real_pg_waiters_one_commit_one_conflict(team):
    row = create(team)
    with ThreadPoolExecutor(max_workers=2) as pool:
        with s.db() as c:
            c.execute('SELECT id FROM collaboration_objects WHERE id=%s FOR UPDATE', (row['id'],))
            first = pool.submit(save, team, row, {'description': 'first'})
            second = pool.submit(save, team, row, {'description': 'second'})
            waits = wait_for_db_waiters(2)
            assert all(item['blockers'] for item in waits)
            print('P5 same-object database wait trace:', json.dumps(waits))
        results = [first.result(15), second.result(15)]
    assert sorted(result.status_code for result in results) == [200, 409]
    rejected = next(result for result in results if result.status_code == 409).json()['detail']
    assert rejected['revision'] == 2 and 'content' not in rejected
    with s.db() as c:
        assert c.execute('SELECT count(*) n FROM collaboration_history WHERE object_id=%s', (row['id'],)).fetchone()['n'] == 2
        assert c.execute("SELECT count(*) n FROM audit_events WHERE target_id=%s AND action='object.save'", (row['id'],)).fetchone()['n'] == 1
        assert c.execute("SELECT count(*) n FROM events WHERE payload->>'object_id'=%s AND payload->>'action'='save'", (row['id'],)).fetchone()['n'] == 1


def test_locked_shot_does_not_lock_other_shot(team):
    a, b = create(team), create(team, team['b'])
    with ThreadPoolExecutor(max_workers=1) as pool:
        with s.db() as c:
            c.execute('SELECT id FROM collaboration_objects WHERE id=%s FOR UPDATE', (a['id'],))
            waiting = pool.submit(save, team, a)
            wait_for_db_waiters(1)
            assert save(team, b, client=team['b']).status_code == 200
            assert not waiting.done()
        assert waiting.result(15).status_code == 200


def test_assign_a_b_a_invalidates_old_epoch_and_keeps_content(team):
    original = create(team)
    row = original
    for target in (team['bid'], team['aid']):
        response = team['admin'].post(url(team, row, '/assign'), json={**version(row), 'assignee_id': target})
        assert response.status_code == 200, response.text
        row = response.json()
    forged_current_revision = {**original, 'revision': row['revision']}
    result = save(team, forged_current_revision)
    assert result.status_code == 409 and result.json()['detail']['type'] == 'assignment'
    assert row['content'] == original['content'] and row['assignment_epoch'] == 3
    assert save(team, row).status_code == 200


def test_timeline_lease_expiry_takeover_old_token_and_locked_clock(team):
    row = create(team, kind='timeline')
    assert save(team, row).status_code == 409
    acquire = {'action': 'acquire', 'assignment_epoch': row['assignment_epoch']}
    result = team['a'].post(url(team, row, '/lease'), json=acquire)
    assert result.status_code == 200, result.text
    first = result.json()
    assert 'lease_hash' not in team['a'].get(url(team, row)).json()
    assert team['a'].post(url(team, row, '/lease'), json=acquire).status_code == 409
    # A deterministic lock schedule: the request starts before expiry, but the
    # holder sets expiry in the past before releasing the real database lock.
    with ThreadPoolExecutor(max_workers=1) as pool:
        with s.db() as c:
            c.execute('SELECT id FROM collaboration_objects WHERE id=%s FOR UPDATE', (row['id'],))
            pending = pool.submit(save, team, row, lease_token=first['token'], lease_epoch=first['lease_epoch'])
            wait_for_db_waiters(1)
            c.execute('UPDATE collaboration_objects SET lease_expires=%s WHERE id=%s', (time.time()-1, row['id']))
        assert pending.result(15).status_code == 409
    second = team['a'].post(url(team, row, '/lease'), json=acquire).json()
    old_release = team['a'].post(url(team, row, '/lease'), json={**acquire, 'action': 'release',
        'token': first['token'], 'lease_epoch': first['lease_epoch']})
    assert old_release.status_code == 409
    assert save(team, row, lease_token=second['token'], lease_epoch=second['lease_epoch']).status_code == 200
    row = team['a'].get(url(team, row)).json()
    takeover = team['admin'].post(url(team, row, '/assign'), json={**version(row), 'assignee_id': team['bid']})
    assert takeover.status_code == 200
    assert team['a'].post(url(team, row, '/lease'), json={**acquire, 'action': 'renew',
        'token': second['token'], 'lease_epoch': second['lease_epoch']}).status_code == 403


def test_review_is_revision_bound_and_restore_adds_revision(team):
    original = create(team)
    row = team['a'].post(url(team, original, '/review'), json={**version(original), 'action': 'submit'}).json()
    changed = save(team, row).json()
    stale = team['admin'].post(url(team, row, '/review'), json={**version(row), 'action': 'approve'})
    assert stale.status_code == 409
    pending = team['a'].post(url(team, changed, '/review'), json={**version(changed), 'action': 'submit'}).json()
    approved = team['admin'].post(url(team, pending, '/review'), json={**version(pending), 'action': 'approve'}).json()
    assert approved['status'] == 'completed'
    edited = save(team, approved, {'description': 'after approval'}).json()
    assert edited['status'] == 'in_progress' and edited['revision'] > approved['revision']
    restored = team['a'].post(url(team, edited, '/restore'), json={**version(edited), 'revision': 1})
    assert restored.status_code == 200, restored.text
    assert restored.json()['revision'] == edited['revision'] + 1
    assert restored.json()['content'] == original['content']
    assert restored.json()['assignee_id'] == team['aid']


def test_viewer_comments_without_content_mutation_and_forgery_rejected(team):
    row = create(team)
    response = team['viewer'].post(url(team, row, '/comments'), json={'body': '请调整镜头节奏'})
    assert response.status_code == 201, response.text
    assert team['viewer'].get(url(team, row)).json()['revision'] == row['revision']
    assert len(team['viewer'].get(url(team, row, '/comments')).json()) == 1
    assert team['viewer'].get(url(team, row, '/history')).status_code == 200
    assert team['a'].post(url(team), json={'kind': 'node', 'content': {}, 'created_by': team['bid']}).status_code == 422
    assert save(team, row, {'assignee_id': team['bid']}).status_code == 422


def test_cross_production_and_episode_ids_are_not_aliases(team):
    row = create(team)
    other = team['admin'].post('/api/projects', json={'name': 'Other P5 Production'}).json()
    path = f"/api/projects/{other['id']}/objects/{row['id']}"
    assert team['admin'].get(path).status_code == 404
    assert team['admin'].patch(path, json={**version(row), 'content': {}}).status_code == 404
    episode = team['admin'].post(f"/api/productions/{team['production']}/episodes", json={'title': 'Second'}).json()
    assert team['a'].get(f"/api/projects/{episode['id']}/objects/{row['id']}").status_code == 404


@pytest.mark.parametrize('mode', ['production_remove', 'workspace_remove', 'viewer', 'deactivate'])
def test_revocation_keeps_content_unassigns_and_expires_credentials(team, mode):
    row = create(team, kind='timeline')
    token = team['a'].post(url(team, row, '/lease'), json={'action': 'acquire', 'assignment_epoch': row['assignment_epoch']}).json()
    if mode == 'production_remove':
        response = team['admin'].delete(f"/api/productions/{team['production']}/members/{team['aid']}")
    elif mode == 'workspace_remove':
        response = team['admin'].delete(f"/api/workspaces/{team['workspace']}/members/{team['aid']}")
    elif mode == 'viewer':
        response = team['admin'].put(f"/api/productions/{team['production']}/members/{team['aid']}", json={'role': 'viewer'})
    else:
        response = team['admin'].patch(f"/api/admin/users/{team['aid']}", json={'is_active': False})
    assert response.status_code == 200, response.text
    latest = team['admin'].get(url(team, row)).json()
    assert latest['content'] == row['content'] and latest['assignee_id'] is None
    assert latest['assignment_epoch'] > row['assignment_epoch']
    assert latest['lease_expires'] is None
    assert team['a'].post(url(team, row, '/lease'), json={'action': 'renew', 'assignment_epoch': row['assignment_epoch'],
        'token': token['token'], 'lease_epoch': token['lease_epoch']}).status_code in {401, 403, 404}
    if mode != 'deactivate':
        if mode == 'workspace_remove':
            add_team_member(team['admin'], team['workspace'], team['aid'])
        add_production_member(team['admin'], team['production'], team['aid'], 'editor')
        latest = team['admin'].post(url(team, latest, '/assign'), json={**version(latest), 'assignee_id': team['aid']}).json()
        assert latest['content'] == row['content']
        assert save(team, {**row, 'revision': latest['revision']}, lease_token=token['token'],
                    lease_epoch=token['lease_epoch']).status_code == 409


@pytest.mark.parametrize('failure', ['unauthorized', 'revision'])
def test_batch_rejection_has_no_partial_content_history_or_events(team, failure):
    first = create(team)
    second = create(team, team['b'] if failure == 'unauthorized' else team['a'])
    if failure == 'revision':
        assert save(team, second).status_code == 200
    before = team['a'].get(url(team, first, '/history')).json()
    response = team['a'].post(url(team) + '/batch', json={'operations': [
        {'id': item['id'], **version(item), 'content': {**item['content'], 'shot': {**item['content']['shot'], 'description': 'batch'}}} for item in (first, second)
    ]})
    assert response.status_code == (403 if failure == 'unauthorized' else 409), response.text
    assert team['a'].get(url(team, first)).json()['content'] == first['content']
    assert team['a'].get(url(team, first, '/history')).json() == before
    with s.db() as c:
        assert c.execute("SELECT count(*) n FROM audit_events WHERE target_id=%s AND action='object.save'", (first['id'],)).fetchone()['n'] == 0


def test_nested_foreign_asset_makes_entire_batch_fail(team):
    from PIL import Image
    image = io.BytesIO()
    Image.new('RGB', (4, 4), 'blue').save(image, format='PNG')
    other = team['admin'].post('/api/projects', json={'name': 'Foreign asset source'}).json()
    uploaded = team['admin'].post(f"/api/projects/{other['id']}/assets",
        files={'file': ('reference.png', image.getvalue(), 'image/png')})
    assert uploaded.status_code == 200, uploaded.text
    foreign_id = uploaded.json()['id']
    first, second = create(team), create(team)
    result = team['a'].post(url(team) + '/batch', json={'operations': [
        {'id': first['id'], **version(first), 'content': {**first['content'], 'shot': {**first['content']['shot'], 'description': 'must roll back'}}},
        {'id': second['id'], **version(second), 'content': {**second['content'], 'shot': {**second['content']['shot'], 'asset_ids': [foreign_id]}}},
    ]})
    assert result.status_code == 422, result.text
    assert foreign_id not in result.text
    assert team['a'].get(url(team, first)).json()['revision'] == 1
    assert len(team['a'].get(url(team, first, '/history')).json()) == 1
