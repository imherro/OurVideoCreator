"""Bounded source-logic probe, NOT a full PostgreSQL/HTTP/Worker reproduction.

Source SHA: 0851dce02e0f22e87f6247b029fd3faedd39e7dd, OurVideoCreator only.
node_ids and topological are copied from the inspected source. The structural
and graph-requirement expressions are the actual expressions in commands().
The object rows and unchanged graph are synthetic inputs supplied by this test.
No repository mutation, network access, database, or user service is involved.
"""
from copy import deepcopy
import json
from pathlib import Path


def node_ids(kind, content):
    if kind == 'node':
        return {content['node']['id']}
    if kind == 'shot':
        return {node['id'] for node in content['nodes']}
    return set()


def topological(nodes,edges):
    ids={n['id'] for n in nodes}
    if len(ids)!=len(nodes): raise ValueError('画布存在重复节点编号')
    children={n:[] for n in ids}; degree={n:0 for n in ids}
    for edge in edges:
        source,target=edge.get('source'),edge.get('target')
        if source not in ids or target not in ids: raise ValueError('连线引用了不存在的节点')
        children[source].append(target); degree[target]+=1
    ready=sorted(n for n in ids if degree[n]==0); result=[]
    while ready:
        current=ready.pop(0);result.append(current)
        for child in children[current]:
            degree[child]-=1
            if degree[child]==0: ready.append(child)
    if len(result)!=len(ids): raise ValueError('画布包含循环连线，请先解除循环后执行')
    return result


def run():
    before = {'shot': {'uid': 'shot-x', 'id': 'X', 'imageNode': 'image-x'},
              'nodes': [{'id': 'image-x', 'type': 'media',
                         'data': {'kind': 'image', 'prompt': 'synthetic'}}]}
    after = deepcopy(before)
    after['shot']['imageNode'] = 'image-x-new'
    after['nodes'][0]['id'] = 'image-x-new'
    locked = {'object-x': {'kind': 'shot', 'content': before}}
    updates = [{'id': 'object-x', 'content': after}]
    creates, deletes = [], []
    structural = bool(creates or deletes) or any(
        node_ids(locked[item['id']]['kind'], item['content']) !=
        node_ids(locked[item['id']]['kind'], locked[item['id']]['content'])
        for item in updates if locked[item['id']]['kind'] in {'shot', 'node'}
    )
    graph_is_required = bool(structural and (
        any(item['kind'] in {'shot', 'node'} for item in creates) or deletes))
    # commands() calls graph_transition only for updates. That helper returns
    # immediately for a non-graph row.
    graphs_actually_validated = [item['id'] for item in updates
                                if locked[item['id']]['kind'] == 'graph']
    edge = {'id': 'edge-xy', 'source': 'image-x', 'target': 'node-y'}
    other = {'id': 'node-y', 'type': 'media', 'data': {'kind': 'text'}}
    before_order = topological(before['nodes'] + [other], [edge])
    try:
        topological(after['nodes'] + [other], [edge])
        after_error = None
    except ValueError as exc:
        after_error = str(exc)
    result = {
        'source_sha': '0851dce02e0f22e87f6247b029fd3faedd39e7dd',
        'execution_scope': 'source expressions + topology function, synthetic rows; no PG/API execution',
        'is_structural': structural,
        'graph_update_required_by_current_branch': graph_is_required,
        'graph_rows_validated_by_current_update_loop': graphs_actually_validated,
        'before_topological_order': before_order,
        'after_node_ids': [n['id'] for n in after['nodes'] + [other]],
        'retained_graph_edge': edge,
        'after_topological_error': after_error,
        'full_application_http_status_observed': None,
    }
    assert structural is True
    assert graph_is_required is False
    assert graphs_actually_validated == []
    assert after_error == '连线引用了不存在的节点'
    return result


if __name__ == '__main__':
    output = run()
    path = Path(__file__).with_name('structural_guard_result.json')
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(path.read_text(encoding='utf-8'))
