"""Classification is organization only: existing media, ACL and read-only compilation remain intact."""
from backend import store as s
from tests.test_motion_references import media, setup_motion
from tests.test_p5_object_transactions import team, admin, clients, clear_auth_rate_limits


def test_motion_category_upload_reclassify_and_access_boundaries(team, media, monkeypatch):
    model, row, asset = setup_motion(team, monkeypatch, media)
    path = '/api/projects/' + team['pid']
    original = media.read_bytes()
    before = team['a'].get(path).json()
    jobs = team['a'].get(path + '/jobs').json()
    old_preview = team['viewer'].post(path + '/video-spec', json={'node_id':'motion-node','model_id':model})
    assert old_preview.status_code == 200, old_preview.text
    endpoint = path + '/assets/' + asset['id']
    assert team['viewer'].patch(endpoint, json={'category':'motion_reference'}).status_code == 403
    changed = team['a'].patch(endpoint, json={'category':'motion_reference'})
    assert changed.status_code == 200, changed.text
    assert changed.json()['category'] == 'motion_reference'
    assert team['viewer'].get('/api/assets/' + asset['id'] + '/file').content == original
    with s.db() as connection:
        stored = connection.execute('SELECT path FROM assets WHERE id=%s', (asset['id'],)).fetchone()
    assert (s.ASSETS / stored['path']).read_bytes() == original
    preview = team['viewer'].post(path + '/video-spec', json={'node_id':'motion-node','model_id':model})
    assert preview.status_code == 200, preview.text
    assert preview.json() == old_preview.json()
    assert team['a'].get(path).json() == before
    assert team['a'].get(path + '/jobs').json() == jobs
    response = team['a'].post(path + '/assets?category=motion_reference', files={'file':('motion.mp4',original,'video/mp4')})
    assert response.status_code == 200, response.text
    assert response.json()['category'] == 'motion_reference'
    assert team['viewer'].post(path + '/assets?category=motion_reference', files={'file':('motion.mp4',original,'video/mp4')}).status_code == 403
    other = team['admin'].post('/api/projects', json={'name':'Unrelated motion category test'}).json()
    assert team['a'].patch('/api/projects/' + other['id'] + '/assets/' + asset['id'], json={'category':'motion_reference'}).status_code == 404
    removed = team['admin'].delete('/api/productions/' + team['production'] + '/members/' + team['aid'])
    assert removed.status_code in (200,204), removed.text
    assert team['a'].get('/api/assets/' + asset['id'] + '/file').status_code == 404
