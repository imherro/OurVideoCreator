"""Small public-API fixtures; no aggregate-save shim or permission bypass."""


def object_version(row):
    return {'expected_revision': row['revision'], 'assignment_epoch': row['assignment_epoch']}


def create_object(client, pid, kind, content):
    response = client.post(f'/api/projects/{pid}/objects', json={'kind': kind, 'content': content})
    assert response.status_code == 201, response.text
    return response.json()


def patch_object(client, pid, row, content):
    return client.patch(f'/api/projects/{pid}/objects/{row["id"]}',
        json={**object_version(row), 'content': content})


def create_visual_cards(client, pid, visual):
    return {cid: create_object(client, pid, 'visual_card', {
        'card': card, 'versions': {vid: v for vid, v in visual['versions'].items() if v['cardId'] == cid},
        'voice_profile': None}) for cid, card in visual['cards'].items()}


def create_node(client, pid, nid, kind='text', **data):
    return create_object(client, pid, 'node', {'node': {
        'id': nid, 'type': 'media', 'data': {'kind': kind, **data}}})


def set_edges(client, pid, edges):
    graph = next(row for row in client.get(f'/api/projects/{pid}/objects').json() if row['kind'] == 'graph')
    response = patch_object(client, pid, graph, {**graph['content'], 'edges': edges})
    assert response.status_code == 200, response.text
    return response.json()
