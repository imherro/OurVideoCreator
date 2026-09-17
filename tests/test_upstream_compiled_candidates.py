"""Compiled video regression through real PG, submission and explicit adoption.

Generated test media is local FFmpeg only; no worker or provider request.
"""
from copy import deepcopy
import subprocess
import uuid

import pytest

from backend import store as s
from backend.media import ffmpeg_executable
from backend.providers.common import register
from tests.test_p5_object_transactions import team, admin, clients, clear_auth_rate_limits, url, version, save
from tests.test_p5_object_candidates import candidate
from tests.platform_model_helpers import publish_test_model


@pytest.mark.parametrize('change', ['none', 'prompt', 'revision'])
def test_duration_compiled_video_adoption_only_marks_real_changes_stale(team, tmp_path, change):
    content = {'shot': {'id': 'S01', 'uid': 'video-shot', 'videoNode': 'video', 'duration': 2},
               'nodes': [{'id': 'video', 'type': 'media', 'data': {
                   'kind': 'video', 'prompt': '人物向前走', 'generation_revision': 3}}]}
    response = team['a'].post(url(team), json={'kind': 'shot', 'content': content})
    assert response.status_code == 201, response.text
    row = response.json()
    model = uuid.uuid4().hex
    publish_test_model(team['admin'], model, kind='video', provider_type='video_api',
                       rules={'duration': {'type': 'integer', 'min': 1, 'max': 30}}, defaults={'duration': 2})
    response = team['a'].post('/api/projects/' + team['pid'] + '/jobs', json={
        'node_id': 'video', 'kind': 'video', 'submission_id': uuid.uuid4().hex,
        'input': {'model_id': model, 'prompt': '人物向前走', 'generation_revision': 3}})
    assert response.status_code == 200, response.text
    job = response.json()
    assert '[镜头时长]' in job['input']['prompt']
    assert not job['input'].get('dialogue_projection')
    path = tmp_path / 'video.mp4'
    generated = subprocess.run([ffmpeg_executable(), '-v', 'error', '-f', 'lavfi', '-i',
        'color=c=blue:s=64x64:r=24:d=2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)],
        capture_output=True, timeout=20)
    assert generated.returncode == 0, generated.stderr
    assert s.job_update(job['id'], status='running')
    asset = register(job, path)
    assert s.job_update(job['id'], status='succeeded', result={'assets': [asset]})
    assert team['a'].get(url(team, row)).json() == row  # success is not automatic adoption
    current = row
    if change != 'none':
        edited = deepcopy(content)
        if change == 'prompt': edited['nodes'][0]['data']['prompt'] = '人物转身离开'
        else: edited['nodes'][0]['data']['generation_revision'] = 4
        response = save(team, row, edited)
        assert response.status_code == 200, response.text
        current = response.json()
        assert team['a'].post(candidate(team, job) + '/adopt', json=version(current)).status_code == 409
    response = team['a'].post(candidate(team, job) + '/adopt', json={**version(current), 'accept_stale': change != 'none'})
    assert response.status_code == 200, response.text
    data = response.json()['target']['content']['nodes'][0]['data']
    assert data['assetId'] == asset['id']
    assert data['stale'] is (change != 'none')
