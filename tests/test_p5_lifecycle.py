"""Public trash/restore APIs, retained content, and real PG lifecycle barriers."""
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from backend import collaboration_lifecycle, store as s
from tests.test_p5_object_transactions import (team, admin, clients, clear_auth_rate_limits,
    create, save, url, wait_for_db_waiters)
from tests.test_p5_owned_content import (base, create_chapter, content, endpoint,
    save as save_owned)
from tests.test_p3_identity_acl import add_production_member
from tests.test_p5_object_candidates import voice_card


def restore(team, kind, target, actor=None):
    return (actor or team['admin']).post(f'/api/trash/{kind}/{target}/restore')


def test_episode_restore_fences_objects_script_metadata_and_lease(team):
    voice_card(team, 'preserved-voice', locked=True)
    shot = create(team)
    timeline = create(team, kind='timeline')
    script = content(team, 'script')
    lease = team['a'].post(url(team, timeline, '/lease'), json={
        'action': 'acquire', 'assignment_epoch': timeline['assignment_epoch']}).json()
    project = team['admin'].get('/api/projects/'+team['pid']).json()
    with s.db() as c:
        shared_before = c.execute('SELECT * FROM collaboration_objects WHERE production_id=%s AND project_id IS NULL',
            (team['production'],)).fetchall()
        assert shared_before
    assert team['admin'].delete('/api/projects/'+team['pid']).status_code == 200
    assert team['a'].get(url(team, shot)).status_code == 404
    assert restore(team, 'project', team['pid']).status_code == 200
    assert restore(team, 'project', team['pid']).status_code == 404
    for old in (shot, timeline):
        latest = team['a'].get(url(team, old)).json()
        assert latest['content'] == old['content']
        assert latest['assignee_id'] == old['assignee_id']
        assert latest['revision'] == old['revision']+2
        assert latest['assignment_epoch'] == old['assignment_epoch']+2
        # Even substituting the current revision cannot revive a pre-trash epoch.
        assert save(team, {**old, 'revision': latest['revision']}).status_code == 409
    latest_timeline = team['a'].get(url(team, timeline)).json()
    assert latest_timeline['lease_user_id'] is None
    assert team['a'].post(url(team, timeline, '/lease'), json={
        'action': 'renew', 'assignment_epoch': latest_timeline['assignment_epoch'],
        'token': lease['token'], 'lease_epoch': lease['lease_epoch']}).status_code == 409
    fresh_lease = team['a'].post(url(team, timeline, '/lease'), json={
        'action': 'acquire', 'assignment_epoch': latest_timeline['assignment_epoch']}).json()
    assert save(team, latest_timeline, lease_token=fresh_lease['token'],
        lease_epoch=fresh_lease['lease_epoch']).status_code == 200
    latest_script = team['a'].get(base(team)+'/episode-scripts/1').json()
    assert latest_script['assignee_id'] == team['aid']
    assert latest_script['revision'] == script['revision']+2
    assert save_owned(team, 'script', script, revision=latest_script['revision']).status_code == 409
    assert save_owned(team, 'script', latest_script).status_code == 200
    assert team['admin'].patch('/api/projects/'+team['pid']+'/metadata', json={
        'expected_revision': project['revision'], 'patch': {'name': 'old page'}}).status_code == 409
    with s.db() as c:
        assert c.execute('SELECT * FROM collaboration_objects WHERE production_id=%s AND project_id IS NULL',
            (team['production'],)).fetchall() == shared_before
        actions = [r['action'] for r in c.execute(
            'SELECT action FROM collaboration_history WHERE object_id=%s ORDER BY revision', (shot['id'],))]
        assert actions[-2:] == ['trash', 'untrash']


@pytest.mark.parametrize('kind', ['source', 'chapter'])
def test_source_restore_retains_owner_and_fences_old_chapter(team, kind):
    chapter = create_chapter(team, team['admin'])
    target = chapter['source_id'] if kind == 'source' else chapter['id']
    body = {'revision': chapter['revision'], 'assignment_epoch': chapter['assignment_epoch']}
    path = base(team)+('/sources/' if kind == 'source' else '/chapters/')+target
    response = team['admin'].request('DELETE', path, json={
        'versions': {chapter['id']: body}} if kind == 'source' else body)
    assert response.status_code == 200, response.text
    assert save_owned(team, 'chapter', chapter, team['admin']).status_code == 404
    assert restore(team, kind, target).status_code == 200
    response = team['admin'].get(endpoint(team, 'chapter', chapter))
    assert response.status_code == 200, response.text
    latest = response.json()
    assert latest['content'] == chapter['content']
    assert latest['assignee_id'] == chapter['assignee_id']
    assert latest['revision'] == chapter['revision']+2
    assert save_owned(team, 'chapter', chapter, team['admin'], revision=latest['revision']).status_code == 409
    assert save_owned(team, 'chapter', latest, team['admin']).status_code == 200


def test_hidden_chapter_remains_hidden_through_source_restore(team):
    chapter = create_chapter(team, team['admin'])
    cid, sid = chapter['id'], chapter['source_id']
    assert team['admin'].request('DELETE', base(team)+'/chapters/'+cid, json={
        'revision': chapter['revision'], 'assignment_epoch': chapter['assignment_epoch']}).status_code == 200
    assert team['admin'].request('DELETE', base(team)+'/sources/'+sid, json={'versions': {}}).status_code == 200
    with s.db() as c:
        before = c.execute('SELECT revision FROM source_chapters WHERE id=%s', (cid,)).fetchone()['revision']
    assert restore(team, 'chapter', cid).status_code == 409
    with s.db() as c:
        assert c.execute('SELECT revision FROM source_chapters WHERE id=%s', (cid,)).fetchone()['revision'] == before
        assert c.execute("SELECT 1 FROM deleted_items WHERE kind='chapter' AND item_id=%s", (cid,)).fetchone()
    assert restore(team, 'source', sid).status_code == 200
    assert team['admin'].get(endpoint(team, 'chapter', chapter)).status_code == 404
    assert restore(team, 'chapter', cid).status_code == 200
    latest = team['admin'].get(endpoint(team, 'chapter', chapter)).json()
    assert latest['content'] == chapter['content'] and latest['revision'] > before


def test_edit_commits_before_trash_and_old_page_cannot_revive(team):
    shot = create(team)
    with ThreadPoolExecutor(max_workers=2) as pool:
        with s.db() as c:
            c.execute('SELECT id FROM collaboration_objects WHERE id=%s FOR UPDATE', (shot['id'],))
            pending_save = pool.submit(save, team, shot, {'description': 'committed before trash'})
            waits = wait_for_db_waiters(1)
            assert waits[0]['blockers']
            pending_trash = pool.submit(team['admin'].delete, '/api/projects/'+team['pid'])
            waits = wait_for_db_waiters(2)
            assert any(r['wait_event'] == 'advisory' for r in waits)
            print('P5 lifecycle row lock then exclusive barrier:', waits)
        assert pending_save.result(15).status_code == 200
        assert pending_trash.result(15).status_code == 200
    assert restore(team, 'project', team['pid']).status_code == 200
    latest = team['a'].get(url(team, shot)).json()
    assert latest['content']['shot']['description'] == 'committed before trash'
    assert latest['revision'] == shot['revision']+3
    assert save(team, shot).status_code == 409


@pytest.mark.parametrize('operation', ['trash', 'restore'])
def test_lifecycle_rechecks_manager_after_request_entry(team, monkeypatch, operation):
    add_production_member(team['admin'], team['production'], team['aid'], 'manager')
    if operation == 'restore':
        assert team['admin'].delete('/api/projects/'+team['pid']).status_code == 200
    entered, release = threading.Event(), threading.Event()
    original = collaboration_lifecycle.authorize
    def paused(c, kind, item_id):
        entered.set()
        assert release.wait(10)
        return original(c, kind, item_id)
    monkeypatch.setattr(collaboration_lifecycle, 'authorize', paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = (pool.submit(team['a'].delete, '/api/projects/'+team['pid']) if operation == 'trash'
            else pool.submit(restore, team, 'project', team['pid'], team['a']))
        try:
            assert entered.wait(10)
            add_production_member(team['admin'], team['production'], team['aid'], 'editor')
        finally:
            release.set()
        response = pending.result(15)
    assert response.status_code == 403, response.text
    with s.db() as c:
        tombstone = c.execute("SELECT 1 FROM deleted_items WHERE kind='project' AND item_id=%s", (team['pid'],)).fetchone()
        assert bool(tombstone) == (operation == 'restore')
