"""Canonical workflow submission: whole-batch ACL and preparation interleavings."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib
import threading
import uuid

import pytest

from backend import object_job_candidates, store as s
from tests.test_p5_object_transactions import (team, admin, clients, clear_auth_rate_limits,
    url, version, save, wait_for_db_waiters)
from tests.test_p5_canonical_integration import graph
from tests.platform_model_helpers import publish_test_model

app_module = importlib.import_module('backend.app')


def nodes(team, other_owner=False):
    model = uuid.uuid4().hex
    publish_test_model(team['admin'], model)
    result = []
    for nid, actor in [('a-first', team['a']), ('z-second', team['b'] if other_owner else team['a'])]:
        response = actor.post(url(team), json={'kind': 'node', 'content': {'node': {
            'id': nid, 'type': 'media', 'data': {'kind': 'text', 'prompt': nid+' prompt', 'model_id': model}}}})
        assert response.status_code == 201, response.text
        result.append(response.json())
    return result


def run(team, ids=None, **extra):
    return team['a'].post('/api/projects/'+team['pid']+'/run', json={
        'submission_id': uuid.uuid4().hex, 'node_ids': ids or ['a-first', 'z-second'], 'exact': True, **extra})


def counts(team):
    with s.db() as c:
        return [c.execute(sql, (team['pid'],)).fetchone()['n'] for sql in (
            'SELECT count(*) n FROM jobs WHERE project_id=%s',
            "SELECT count(*) n FROM events WHERE project_id=%s AND payload->>'type'='job'",
            'SELECT count(*) n FROM job_private jp JOIN jobs j ON j.id=jp.job_id WHERE j.project_id=%s')]


def test_mixed_owner_run_rolls_back_even_first_prepared_job(team, monkeypatch):
    nodes(team, other_owner=True)
    original = app_module.create_job_record
    inserted = []
    def observed(*args, **kwargs):
        result = original(*args, **kwargs)
        inserted.append(result['id'])
        return result
    monkeypatch.setattr(app_module, 'create_job_record', observed)
    before = counts(team)
    response = run(team)
    assert response.status_code == 403, response.text
    assert len(inserted) == 1  # Real insert occurred, but no partial batch committed.
    assert counts(team) == before
    with s.db() as c:
        assert not c.execute('SELECT 1 FROM jobs WHERE id=%s', (inserted[0],)).fetchone()


@pytest.mark.parametrize('change', ['node', 'graph', 'assignment', 'metadata'])
def test_preparation_snapshot_change_rejects_whole_run(team, monkeypatch, change):
    first, second = nodes(team)
    structure = graph(team)
    entered, release = threading.Event(), threading.Event()
    original = object_job_candidates.lock_batch
    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(15)
        return original(*args, **kwargs)
    monkeypatch.setattr(object_job_candidates, 'lock_batch', paused)
    before = counts(team)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(run, team)
        try:
            assert entered.wait(10)
            if change == 'node':
                value = deepcopy(second['content']);value['node']['data']['prompt'] = 'new prompt'
                updated = save(team, second, value)
            elif change == 'assignment':
                updated = team['admin'].post(url(team, second, '/assign'), json={
                    **version(second), 'assignee_id': team['bid']})
            elif change == 'graph':
                value = deepcopy(structure['content'])
                value['edges'] = [{'id': 'new-dependency', 'source': 'a-first', 'target': 'z-second'}]
                updated = save(team, structure, value)
            else:
                project = team['admin'].get('/api/projects/'+team['pid']).json()
                updated = team['admin'].patch('/api/projects/'+team['pid']+'/metadata', json={
                    'expected_revision': project['revision'], 'patch': {'brief': 'new brief'}})
            assert updated.status_code == 200, updated.text
        finally:
            release.set()
        response = pending.result(15)
    assert response.status_code == 409, response.text
    assert counts(team) == before
    if change == 'node':
        assert team['a'].get(url(team, second)).json()['content']['node']['data']['prompt'] == 'new prompt'
    # A fresh submission is allowed; reassignment requires explicit takeover.
    if change == 'assignment':
        current = updated.json()
        takeover = team['admin'].post(url(team, current, '/assign'), json={**version(current), 'assignee_id': team['aid']})
        assert takeover.status_code == 200, takeover.text
    response = run(team)
    assert response.status_code == 200, response.text
    assert response.json()['count'] == 2


def test_reference_is_readable_but_running_other_owners_parent_is_forbidden(team):
    first, second = nodes(team, other_owner=True)
    structure = graph(team);value = deepcopy(structure['content'])
    value['edges'] = [{'id': 'reference', 'source': 'z-second', 'target': 'a-first'}]
    assert save(team, structure, value).status_code == 200
    before = counts(team)
    # Expanding the graph would generate the other editor's node as well.
    assert run(team, ['a-first'], exact=False).status_code == 403
    assert counts(team) == before
    response = run(team, ['a-first'])
    assert response.status_code == 200, response.text
    assert response.json()['count'] == 1
    job = team['a'].get('/api/jobs/'+response.json()['job_ids'][0]).json()
    assert job['collaboration']['target']['id'] == first['id']
    assert second['id'] in {r['id'] for r in job['collaboration']['references']}
    assert job['input']['upstream_job_ids'] == []
    assert team['b'].get(url(team, second)).json() == second


def test_two_real_pg_waiting_runs_preserve_independent_batch_receipts(team):
    nodes(team)
    structure = graph(team)
    with ThreadPoolExecutor(max_workers=2) as pool:
        with s.db() as c:
            c.execute('SELECT id FROM collaboration_objects WHERE id=%s FOR UPDATE', (structure['id'],))
            pending = [pool.submit(run, team, ids) for ids in (['a-first', 'z-second'], ['z-second', 'a-first'])]
            waits = wait_for_db_waiters(2)
            assert all(r['blockers'] for r in waits)
            print('P5 run batch PostgreSQL wait chain:', waits)
        responses = [p.result(20) for p in pending]
    assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
    ids = [jid for r in responses for jid in r.json()['job_ids']]
    assert len(ids) == len(set(ids)) == 4
    assert counts(team) == [4, 4, 4]
