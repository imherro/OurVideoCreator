"""FINAL-FUNC-01: real-PG cross-episode media lifecycle and ACL gap."""
from tests.test_p3_identity_acl import admin, clients, clear_auth_rate_limits, png_bytes, register
from tests.test_p5_object_transactions import team, version


def test_cross_episode_timeline_keeps_referenced_media_usable(team, clients):
    manager, member = team['admin'], team['a']
    origin, production = team['pid'], team['production']
    target = manager.post(f'/api/productions/{production}/episodes', json={'title': 'shared media target'}).json()['id']
    uploaded = member.post(f'/api/projects/{origin}/assets',
        files={'file': ('shared.png', png_bytes(), 'image/png')})
    assert uploaded.status_code == 200
    asset = uploaded.json()['id']
    obj = next(row for row in manager.get(f'/api/projects/{target}/objects').json() if row['kind'] == 'timeline')
    route = f'/api/projects/{target}/objects/{obj["id"]}'
    assigned = manager.post(route + '/assign', json={**version(obj), 'assignee_id': team['aid']})
    assert assigned.status_code == 200
    obj = assigned.json()
    lease = member.post(route + '/lease', json={'action': 'acquire', 'assignment_epoch': obj['assignment_epoch']}).json()
    credentials = {'lease_token': lease['token'], 'lease_epoch': lease['lease_epoch']}
    content = {'timeline': {'version': 2, 'tracks': [{'id': 'video', 'type': 'video', 'elements': [
        {'id': 'shared', 'type': 'image', 'start': 0, 'end': 2,
         'props': {'src': f'/api/assets/{asset}/file'}, 'metadata': {'assetId': asset}}]}]}}
    saved = member.patch(route, json={**version(obj), **credentials, 'content': content})
    assert saved.status_code == 200, saved.text
    assert member.get(f'/api/assets/{asset}/file').content == png_bytes()
    assert team['b'].get(f'/api/assets/{asset}/file').status_code == 200
    outsider, _, _ = register(manager, clients, nickname='FINAL outsider')
    assert outsider.get(f'/api/assets/{asset}/file').status_code == 404
    assert outsider.get(route).status_code == 404
    # A recoverable delete must not turn the other episode's live timeline into
    # a dangling reference. The current contract chooses an explicit refusal.
    rejected = manager.delete(f'/api/projects/{origin}/assets/{asset}')
    assert rejected.status_code == 409, rejected.text
    assert '引用' in rejected.json()['detail']
    assert member.get(route).json()['content'] == content
    assert member.get(f'/api/assets/{asset}/file').content == png_bytes()
    # Trashing only the origin episode keeps the shared production asset usable.
    assert manager.delete(f'/api/projects/{origin}').status_code == 200
    assert member.get(f'/api/assets/{asset}/file').content == png_bytes()
    assert member.get(route).json()['content'] == content
    # Once the last live reference is removed, normal soft-delete/restore works.
    cleared = member.patch(route, json={**version(saved.json()), **credentials,
        'content': {'timeline': {'version': 2, 'tracks': []}}})
    assert cleared.status_code == 200, cleared.text
    assert manager.delete(f'/api/projects/{target}/assets/{asset}').status_code == 200
    assert member.get(f'/api/assets/{asset}/file').status_code == 404
    # Restore the source container before restoring its soft-deleted asset.
    assert manager.post(f'/api/trash/project/{origin}/restore').status_code == 200
    assert manager.post(f'/api/trash/asset/{asset}/restore').status_code == 200
    assert member.get(f'/api/assets/{asset}/file').content == png_bytes()
