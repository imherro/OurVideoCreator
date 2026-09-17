"""Deprecated visual versions restore through object history, ACL and CAS."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from backend import store as s
from tests.test_p3_r2_interleavings import wait_for_db_waiters
from tests.test_p5_object_transactions import (
    admin,
    clients,
    clear_auth_rate_limits,
    save,
    team,
    url,
    version,
)


VERSION_ID = 'restore-hero-v1'


def create_visual(team, status='locked'):
    content = {
        'card': {
            'id': 'restore-hero', 'kind': 'character', 'name': '可恢复角色',
            'parentCardId': None, 'currentVersionId': VERSION_ID,
            'status': 'active', 'source': {'type': 'script_extraction'},
        },
        'versions': {
            VERSION_ID: {
                'id': VERSION_ID, 'cardId': 'restore-hero', 'version': 1,
                'parentVersionId': None, 'status': status,
                'spec': {'description': '银灰色长衣', 'attributes': [{'name': '发色', 'value': '黑'}]},
                'invariants': ['脸型不变'], 'references': [],
                'createdAt': 1, 'provenance': {'source': 'test'},
            },
        },
        'voice_profile': None,
    }
    response = team['a'].post(url(team), json={'kind': 'visual_card', 'content': content})
    assert response.status_code == 201, response.text
    return response.json()


def deprecate(team, row):
    content = deepcopy(row['content'])
    content['versions'][VERSION_ID]['status'] = 'deprecated'
    response = save(team, row, content)
    assert response.status_code == 200, response.text
    return response.json()


def restore_url(team, row):
    return url(team, row, f'/visual-versions/{VERSION_ID}/restore')


@pytest.mark.parametrize('previous_status', ['locked', 'draft'])
def test_restore_changes_only_proven_status_and_is_visible_in_every_episode(team, previous_status):
    original = create_visual(team, previous_status)
    deprecated = deprecate(team, original)
    before = deepcopy(deprecated['content'])

    second = team['admin'].post(
        f"/api/productions/{team['production']}/episodes",
        json={'title': '恢复共享视觉的另一集', 'creation_mode': 'direct'},
    )
    assert second.status_code == 200, second.text

    response = team['a'].post(restore_url(team, deprecated), json=version(deprecated))
    assert response.status_code == 200, response.text
    restored = response.json()
    assert restored['revision'] == deprecated['revision'] + 1
    assert restored['assignment_epoch'] == deprecated['assignment_epoch']
    assert restored['assignee_id'] == team['aid']
    expected = deepcopy(before)
    expected['versions'][VERSION_ID]['status'] = previous_status
    assert restored['content'] == expected

    shared = next(row for row in team['a'].get(
        f"/api/projects/{second.json()['id']}/objects").json() if row['id'] == restored['id'])
    assert shared['content'] == expected

    with s.db() as connection:
        actions = [row['action'] for row in connection.execute(
            'SELECT action FROM collaboration_history WHERE object_id=%s ORDER BY revision',
            (restored['id'],))]
        assert actions == ['create', 'save', 'visual.restore']
        assert connection.execute("""SELECT count(*) n FROM audit_events
            WHERE target_id=%s AND action='object.visual.restore'""", (restored['id'],)).fetchone()['n'] == 1
        assert connection.execute("""SELECT count(*) n FROM events
            WHERE payload->>'object_id'=%s AND payload->>'action'='visual.restore'""",
            (restored['id'],)).fetchone()['n'] == 2


def test_restore_requires_current_owner_and_exact_object_generation(team):
    deprecated = deprecate(team, create_visual(team))
    body = version(deprecated)
    assert team['b'].post(restore_url(team, deprecated), json=body).status_code == 403
    assert team['admin'].post(restore_url(team, deprecated), json=body).status_code == 403
    assert team['viewer'].post(restore_url(team, deprecated), json=body).status_code == 403

    stale = {**body, 'expected_revision': body['expected_revision'] - 1}
    response = team['a'].post(restore_url(team, deprecated), json=stale)
    assert response.status_code == 409
    assert response.json()['detail']['revision'] == deprecated['revision']
    assert team['a'].get(url(team, deprecated)).json() == deprecated

    missing = team['a'].post(
        url(team, deprecated, '/visual-versions/missing-version/restore'), json=body)
    assert missing.status_code == 404
    assert team['a'].post(restore_url(team, deprecated), json=body).status_code == 200


def test_concurrent_restore_same_revision_commits_once(team):
    deprecated = deprecate(team, create_visual(team))
    with ThreadPoolExecutor(max_workers=2) as pool:
        with s.db() as connection:
            connection.execute('SELECT id FROM collaboration_objects WHERE id=%s FOR UPDATE', (deprecated['id'],))
            first = pool.submit(team['a'].post, restore_url(team, deprecated), json=version(deprecated))
            second = pool.submit(team['a'].post, restore_url(team, deprecated), json=version(deprecated))
            waits = wait_for_db_waiters(2)
            assert all(row['blockers'] for row in waits)
        results = [first.result(15), second.result(15)]
    assert sorted(result.status_code for result in results) == [200, 409]
    current = team['a'].get(url(team, deprecated)).json()
    assert current['revision'] == deprecated['revision'] + 1
    assert current['content']['versions'][VERSION_ID]['status'] == 'locked'
    with s.db() as connection:
        assert connection.execute("""SELECT count(*) n FROM collaboration_history
            WHERE object_id=%s AND action='visual.restore'""", (deprecated['id'],)).fetchone()['n'] == 1
