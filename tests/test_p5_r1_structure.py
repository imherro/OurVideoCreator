"""Regression reproduction prepared while the P5 external review is running.

The reviewed runtime is unchanged. Ordinary A owns a shot source; ordinary B
owns its downstream target. Removing A's attached source without a graph
version must not leave B's persisted dependency pointing at a missing node.
"""
import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend import store as s
from backend.workflows import topological
from tests.test_p3_r2_interleavings import wait_for_db_waiters
from tests.test_p5_review_child_identity import _counts

from tests.test_p5_object_transactions import (
    admin, clients, clear_auth_rate_limits, team, url, version,
)


def test_attached_node_removal_requires_atomic_graph_version(team):
    source_content = {
        'shot': {'id': 'source-shot', 'uid': 'source-shot', 'imageNode': 'source-image'},
        'nodes': [{'id': 'source-image', 'type': 'image', 'data': {'prompt': 'source'}}],
    }
    created = team['a'].post(url(team), json={'kind': 'shot', 'content': source_content})
    assert created.status_code == 201, created.text
    source = created.json()
    target = team['b'].post(url(team), json={'kind': 'node', 'content': {
        'node': {'id': 'b-target', 'type': 'image', 'data': {'prompt': 'target'}}}})
    assert target.status_code == 201, target.text
    graph = next(row for row in team['b'].get(url(team)).json() if row['kind'] == 'graph')
    graph_content = copy.deepcopy(graph['content'])
    edge = {'id': 'source-to-b', 'source': 'source-image', 'target': 'b-target'}
    graph_content['edges'].append(edge)
    linked = team['b'].patch(url(team, graph), json={**version(graph), 'content': graph_content})
    assert linked.status_code == 200, linked.text
    graph = linked.json()
    removed = {'shot': {'id': 'source-shot', 'uid': 'source-shot'}, 'nodes': []}
    response = team['a'].patch(url(team, source), json={**version(source), 'content': removed})
    after_source = team['a'].get(url(team, source)).json()
    after_graph = team['b'].get(url(team, graph)).json()
    print('P5 attached-node graph guard:', json.dumps({
        'response_status': response.status_code,
        'source_revision_before': source['revision'], 'source_revision_after': after_source['revision'],
        'source_nodes_after': after_source['content']['nodes'],
        'graph_revision_before': graph['revision'], 'graph_revision_after': after_graph['revision'],
        'edges_after': after_graph['content']['edges'],
    }))
    assert response.status_code == 422, response.text
    assert after_source == source
    assert after_graph == graph


def pair(team, foreign=False):
    response = team['a'].post(url(team), json={'kind': 'shot', 'content': {
        'shot': {'id': 'X', 'uid': 'X', 'imageNode': 'child'},
        'nodes': [{'id': 'child', 'type': 'media', 'data': {'kind': 'image'}}]}})
    assert response.status_code == 201, response.text
    shot = response.json()
    owner = team['b'] if foreign else team['a']
    response = owner.post(url(team), json={'kind': 'node', 'content': {
        'node': {'id': 'target', 'type': 'media', 'data': {'kind': 'text'}}}})
    assert response.status_code == 201, response.text
    graph = next(row for row in owner.get(url(team)).json() if row['kind'] == 'graph')
    content = copy.deepcopy(graph['content'])
    content.update(edges=[{'id': 'edge', 'source': 'child', 'target': 'target'}],
                   positions={'child': {'x': 1, 'y': 2}}, nodeOrder=['child', 'target'])
    response = owner.patch(url(team, graph), json={**version(graph), 'content': content})
    assert response.status_code == 200, response.text
    return shot, response.json()


def identity_update(shot, graph, mode='rename'):
    child = copy.deepcopy(shot['content'])
    structure = copy.deepcopy(graph['content'])
    if mode == 'add':
        child['shot']['videoNode'] = 'new-child'
        child['nodes'].append({'id': 'new-child', 'type': 'media', 'data': {'kind': 'video'}})
        structure['nodeOrder'].append('new-child')
    else:
        structure['positions'].pop('child')
        structure['nodeOrder'].remove('child')
        if mode == 'remove':
            child['shot'].pop('imageNode')
            child['nodes'] = []
            structure['edges'] = []
        else:
            child['shot']['imageNode'] = 'new-child'
            child['nodes'][0]['id'] = 'new-child'
            structure['nodeOrder'].insert(0, 'new-child')
            structure['positions']['new-child'] = {'x': 1, 'y': 2}
            structure['edges'][0]['source'] = 'new-child'
    return [dict(id=row['id'], **version(row), content=content)
            for row, content in [(shot, child), (graph, structure)]]


def snapshot(team):
    return team['a'].get(url(team)).json(), _counts(team)


def topology(team):
    document = team['a'].get('/api/projects/' + team['pid']).json()['document']
    topological(document['nodes'], document['edges'])
    return document


@pytest.mark.parametrize('mode', ['add', 'remove', 'rename'])
def test_identity_changes_require_graph_but_valid_atomic_changes_work(team, mode):
    shot, graph = pair(team)
    updates = identity_update(shot, graph, mode)
    before = snapshot(team)
    rejected = team['a'].post(url(team) + '/commands', json={'updates': updates[:1]})
    assert rejected.status_code == 422, rejected.text
    assert snapshot(team) == before
    accepted = team['a'].post(url(team) + '/commands', json={'updates': updates})
    assert accepted.status_code == 200, accepted.text
    assert all(row['revision'] == original['revision'] + 1
               for row, original in zip(accepted.json()['updated'], [shot, graph]))
    topology(team)
    # A history restore is not allowed to silently resurrect/remove child IDs.
    current = accepted.json()['updated'][0]
    before_restore = snapshot(team)
    restored = team['a'].post(url(team, current, '/restore'), json={**version(current), 'revision': 1})
    assert restored.status_code == 422, restored.text
    assert snapshot(team) == before_restore


@pytest.mark.parametrize('invalid', ['edges', 'positions', 'nodeOrder', 'shotOrder', 'stale'])
def test_graph_presence_alone_cannot_bypass_integrity_or_revision(team, invalid):
    shot, graph = pair(team)
    updates = identity_update(shot, graph)
    if invalid == 'stale':
        updates[1]['expected_revision'] -= 1
    elif invalid == 'shotOrder':
        updates[1]['content']['shotOrder'].append('absent-shot')
    else:
        updates[1]['content'][invalid] = copy.deepcopy(graph['content'][invalid])
    before = snapshot(team)
    response = team['a'].post(url(team) + '/commands', json={
        'creates': [{'kind': 'node', 'content': {'node': {'id': 'must-rollback', 'type': 'media', 'data': {}}}}],
        'updates': updates})
    assert response.status_code == (409 if invalid == 'stale' else 422), response.text
    assert snapshot(team) == before
    topology(team)


@pytest.mark.parametrize('mode', ['remove', 'rename'])
def test_valid_graph_cleanup_still_requires_foreign_target_permission(team, mode):
    shot, graph = pair(team, foreign=True)
    before = snapshot(team)
    response = team['a'].post(url(team) + '/commands', json={'updates': identity_update(shot, graph, mode)})
    assert response.status_code == 403, response.text
    assert snapshot(team) == before
    topology(team)


def test_graph_and_child_change_compete_through_real_pg_waiters(team):
    shot, graph = pair(team)
    updates = identity_update(shot, graph)
    layout = copy.deepcopy(graph['content'])
    layout['positions']['child']['x'] = 99
    before_counts = _counts(team)
    with ThreadPoolExecutor(max_workers=2) as pool:
        with s.db() as c:
            c.execute('SELECT id FROM collaboration_objects WHERE id=%s FOR UPDATE', (graph['id'],))
            structural = pool.submit(team['a'].post, url(team) + '/commands', json={'updates': updates})
            graphical = pool.submit(team['a'].patch, url(team, graph), json={**version(graph), 'content': layout})
            waits = wait_for_db_waiters(2)
            print('P5-R1 graph/child PG wait trace:', json.dumps(waits))
        results = [structural.result(15), graphical.result(15)]
    assert sorted(response.status_code for response in results) == [200, 409]
    structural_won = results[0].status_code == 200
    after_shot = team['a'].get(url(team, shot)).json()
    after_graph = team['a'].get(url(team, graph)).json()
    assert after_shot['revision'] == shot['revision'] + int(structural_won)
    assert after_graph['revision'] == graph['revision'] + 1
    assert after_shot['content'] == (updates[0]['content'] if structural_won else shot['content'])
    assert after_graph['content'] == (updates[1]['content'] if structural_won else layout)
    after_counts = _counts(team)
    assert {key: after_counts[key] - value for key, value in before_counts.items()} == {
        'history': 1 + int(structural_won), 'audit': 1 + int(structural_won), 'events': 1 + int(structural_won)}
    print('P5-R1 graph/child commit results:', [response.status_code for response in results])
    topology(team)
