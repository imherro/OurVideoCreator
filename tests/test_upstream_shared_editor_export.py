"""A same-production asset must remain exportable after explicit cross-EP use."""
import uuid
import subprocess
import copy
import pytest

from backend import store as s
from backend.worker import Worker
from backend.media import ffmpeg_executable
from tests.test_p3_identity_acl import png_bytes
from tests.test_p5_object_transactions import team, admin, clients, clear_auth_rate_limits, version


def test_same_production_cross_episode_editor_export_is_real_ffmpeg(team):
    target = team['admin'].post(f"/api/productions/{team['production']}/episodes", json={'title': 'Export target'}).json()['id']
    uploaded = team['a'].post(f"/api/projects/{team['pid']}/assets", files={'file': ('shared.png', png_bytes(), 'image/png')})
    assert uploaded.status_code == 200, uploaded.text
    asset = uploaded.json()['id']
    rows = team['admin'].get(f'/api/projects/{target}/objects').json()
    obj = next(row for row in rows if row['kind'] == 'timeline')
    route = f'/api/projects/{target}/objects/{obj["id"]}'
    obj = team['admin'].post(route + '/assign', json={**version(obj), 'assignee_id': team['aid']}).json()
    lease = team['a'].post(route + '/lease', json={'action': 'acquire', 'assignment_epoch': obj['assignment_epoch']}).json()
    timeline = {'version': 2, 'tracks': [{'id': 'v', 'type': 'element', 'elements': [
        {'id': 'shared', 'type': 'image', 's': 0, 'e': .5, 'props': {'srcAssetId': asset},
         'metadata': {'assetId': asset}, 'frame': {'x': 0, 'y': 0, 'size': [64, 64]}}]}]}
    saved = team['a'].patch(route, json={**version(obj), 'lease_token': lease['token'], 'lease_epoch': lease['lease_epoch'],
                                        'content': {'timeline': timeline}})
    assert saved.status_code == 200, saved.text
    response = team['a'].post(f'/api/projects/{target}/jobs', json={
        'kind': 'export', 'node_id': 'export', 'submission_id': uuid.uuid4().hex,
        'input': {'render_mode': 'editor', 'editor_timeline': timeline, 'resolution': '64x64'}})
    assert response.status_code == 200, response.text
    job = response.json()
    assert s.job_update(job['id'], status='running')
    result = Worker().export(job)
    assert result['render']['visual_count'] == 1
    with s.db() as c:
        row = c.execute('SELECT * FROM assets WHERE id=%s', (result['assets'][0]['id'],)).fetchone()
    assert row['project_id'] == target
    decoded = subprocess.run([ffmpeg_executable(), '-v', 'error', '-i', str(s.ASSETS / row['path']),
        '-frames:v', '1', '-f', 'null', '-'], capture_output=True, timeout=20)
    assert decoded.returncode == 0, decoded.stderr

    # A forged production in the request/job must not authorize foreign media.
    foreign = team['admin'].post('/api/projects', json={'name': 'Foreign production'}).json()
    foreign_asset = team['admin'].post(f"/api/projects/{foreign['id']}/assets",
        files={'file': ('foreign.png', png_bytes(), 'image/png')}).json()['id']
    forged = copy.deepcopy(job)
    forged['production_id'] = foreign['production_id']
    forged['input']['production_id'] = foreign['production_id']
    clip = forged['input']['editor_timeline']['tracks'][0]['elements'][0]
    clip['props']['srcAssetId'] = clip['metadata']['assetId'] = foreign_asset
    canonical = team['a'].post(f'/api/projects/{target}/jobs', json={
        'kind': 'export', 'node_id': 'export', 'submission_id': uuid.uuid4().hex, 'input': forged['input']})
    # Admission freezes the target object/version and production, not every
    # submitted render field. Foreign media must still fail at execution.
    assert canonical.status_code == 200, canonical.text
    queued = canonical.json()
    assert queued['production_id'] == team['production']
    saved_clip = team['a'].get(route).json()['content']['timeline']['tracks'][0]['elements'][0]
    assert saved_clip['props']['srcAssetId'] == saved_clip['metadata']['assetId'] == asset
    with pytest.raises(ValueError, match='属于其他项目'):
        Worker().export(queued)
    with pytest.raises(ValueError, match='属于其他项目'):
        Worker().export(forged)
