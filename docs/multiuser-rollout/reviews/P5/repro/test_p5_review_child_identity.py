"""Proposed red/green regression: NOT executed by the external reviewer.

Run only inside OurVideoCreator's existing isolated PostgreSQL pytest setup.
Copy into tests/ in the collaboration repository. Do not point pytest at a user
or retained browser database. Uses synthetic objects and no Provider requests.
The final assertion is the REQUIRED fixed behavior, so baseline is expected red.
"""
from copy import deepcopy
import json
import pytest
from backend import store as s
from backend.workflows import topological
from tests.test_p5_object_transactions import (
    team, admin, clients, clear_auth_rate_limits, url, version,
)


def _new(client, team, kind, content):
    response = client.post(url(team), json={'kind': kind, 'content': content})
    assert response.status_code == 201, response.text
    return response.json()


def _graph(team):
    return next(row for row in team['a'].get(url(team)).json() if row['kind'] == 'graph')


def _counts(team):
    with s.db() as c:
        return {
            'history': c.execute('''SELECT COUNT(*) n FROM collaboration_history h
                JOIN collaboration_objects o ON o.id=h.object_id
                WHERE o.production_id=%s''', (team['production'],)).fetchone()['n'],
            'audit': c.execute('SELECT COUNT(*) n FROM audit_events WHERE production_id=%s',
                               (team['production'],)).fetchone()['n'],
            'events': c.execute('SELECT COUNT(*) n FROM events WHERE production_id=%s',
                                (team['production'],)).fetchone()['n'],
        }


@pytest.mark.parametrize('entry', ['patch', 'batch', 'commands'])
def test_child_identity_cannot_leave_a_foreign_owned_dependency_dangling(team, entry):
    shot = _new(team['a'], team, 'shot', {
        'shot': {'id': 'X', 'uid': 'shot-x', 'description': 'original',
                 'imageNode': 'image-x', 'pipeline': {'imageNodeId': 'image-x'}},
        'nodes': [{'id': 'image-x', 'type': 'media',
                   'data': {'kind': 'image', 'prompt': 'synthetic'}}],
    })
    _new(team['b'], team, 'node', {
        'node': {'id': 'node-y', 'type': 'media', 'data': {'kind': 'text', 'prompt': 'synthetic'}}
    })
    graph = _graph(team)
    content = deepcopy(graph['content'])
    content['edges'].append({'id': 'edge-xy', 'source': 'image-x', 'target': 'node-y'})
    # B owns the dependent target, so creating this dependency is legitimate.
    result = team['b'].patch(url(team, graph), json={**version(graph), 'content': content})
    assert result.status_code == 200, result.text
    graph = result.json()
    # Control: A must not directly remove B's dependency through the graph API.
    removed = deepcopy(graph['content'])
    removed['edges'] = []
    direct = team['a'].patch(url(team, graph), json={**version(graph), 'content': removed})
    assert direct.status_code == 403, direct.text
    before_counts = _counts(team)
    before_graph = _graph(team)
    before_shot = team['a'].get(url(team, shot)).json()
    after = deepcopy(shot['content'])
    after['shot']['imageNode'] = 'image-x-new'
    after['shot']['pipeline']['imageNodeId'] = 'image-x-new'
    after['nodes'][0]['id'] = 'image-x-new'
    op = {'id': shot['id'], **version(shot), 'content': after}
    if entry == 'patch':
        response = team['a'].patch(url(team, shot), json={k: v for k, v in op.items() if k != 'id'})
    elif entry == 'batch':
        response = team['a'].post(url(team) + '/batch', json={'operations': [op]})
    else:
        response = team['a'].post(url(team) + '/commands', json={'updates': [op]})
    latest_shot = team['a'].get(url(team, shot)).json()
    latest_graph = _graph(team)
    read = team['b'].get('/api/projects/' + team['pid'])
    assert read.status_code == 200, read.text
    document = read.json()['document']
    graph_error = None
    try:
        topological(document['nodes'], document['edges'])
    except ValueError as exc:
        graph_error = str(exc)
    observation = {
        'entry': entry, 'status': response.status_code,
        'shot_revision_before': before_shot['revision'],
        'shot_revision_after': latest_shot['revision'],
        'graph_revision_before': before_graph['revision'],
        'graph_revision_after': latest_graph['revision'],
        'topology_error': graph_error,
    }
    print(json.dumps(observation, ensure_ascii=False))
    assert response.status_code in (409, 422), observation
    assert latest_shot == before_shot
    assert latest_graph == before_graph
    assert graph_error is None
    assert _counts(team) == before_counts
