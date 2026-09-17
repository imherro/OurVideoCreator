"""HC fixed dialogue: real PG/HTTP ownership/adoption, local FFmpeg, fake egress."""
import json
import subprocess
import uuid
from urllib.parse import urlsplit, parse_qs

import httpx
import pytest

from backend import model_validation, store as s
from backend.media import ffmpeg_executable
from backend.provider_assets import valid_signature
from backend.providers import hc_atom
from backend.worker import Worker
from tests.egress_helpers import mock_egress, public_test_dns
from tests.platform_model_helpers import publish_test_model
from tests.test_p5_object_transactions import team, admin, clients, clear_auth_rate_limits, url, version
from tests.test_p5_object_candidates import audio_model, voice_card, audio_result, candidate


@pytest.mark.parametrize('model,allowed', [
    ('doubao-seedance-2.5', True), ('dreamina-seedance-2.0-260128', True),
    ('doubao-seedance-1.5', False), ('kling-video', False),
    ('doubao-seedance-2.50', False), ('private-alias', False),
])
def test_audio_capability_requires_verified_hc_protocol(model, allowed):
    body = {'name': 'Test', 'upstream_model': model, 'capabilities': {'audio_reference': True}}
    if allowed:
        assert model_validation.model_definition(body, {'type': 'hc_atom'}, 'video')['capabilities']['audio_reference']
    else:
        with pytest.raises(ValueError, match='参考音频协议'):
            model_validation.model_definition(body, {'type': 'hc_atom'}, 'video')


def setup_dialogue(team, monkeypatch, *, public=True, capability=True):
    public_test_dns(monkeypatch)
    speech = audio_model(team)
    voice_card(team, speech, locked=True)
    model = uuid.uuid4().hex
    publish_test_model(team['admin'], model, kind='video', provider_type='hc_atom',
        upstream_model='doubao-seedance-2.5', url='https://hc.example',
        options={'public_base_url': 'https://studio.example'} if public else {},
        capabilities={'audio_reference': capability},
        defaults={'duration': 4, 'generate_audio': False},
        rules={'duration': {'type': 'integer', 'min': 4, 'max': 30}, 'generate_audio': {'type': 'boolean'}})
    dialogue = {'id': 'hc-line', 'characterCardId': 'hero', 'text': '这是已保存的对白'}
    content = {'shot': {'id': 'S01', 'uid': 'hc-shot', 'videoNode': 'hc-video',
                        'duration': 4, 'dialogues': [dialogue]},
               'nodes': [{'id': 'hc-video', 'type': 'media', 'data': {
                   'kind': 'video', 'model_id': model, 'prompt': '人物说话'}}]}
    response = team['a'].post(url(team), json={'kind': 'shot', 'content': content})
    assert response.status_code == 201, response.text
    row = response.json()
    path = '/api/projects/' + team['pid']
    response = team['a'].post(path + '/audio-jobs', json={'jobs': [{
        'node_id': 'dialogue:hc-line', 'kind': 'audio', 'submission_id': uuid.uuid4().hex,
        'input': {'model_id': speech, 'prompt': dialogue['text'], 'voice_type': 'test-voice',
                  'dialogue': {**dialogue, 'shotUid': 'hc-shot', 'voiceVersion': 1}},
    }]})
    assert response.status_code == 200, response.text
    return row, model, response.json()['jobs'][0]


def submit_video(team, model, *, batch=False, actor=None, extra=None):
    path = '/api/projects/' + team['pid']
    if batch:
        return (actor or team['a']).post(path + '/run', json={
            'submission_id': uuid.uuid4().hex, 'node_ids': ['hc-video'], 'exact': True})
    return (actor or team['a']).post(path + '/jobs', json={
        'node_id': 'hc-video', 'kind': 'video', 'submission_id': uuid.uuid4().hex,
        'input': {'model_id': model, 'prompt': '人物说话', **(extra or {})}})


@pytest.mark.parametrize('batch', [False, True])
def test_adopted_dialogue_signed_reference_single_and_batch(team, monkeypatch, tmp_path, batch):
    row, model, audio_job = setup_dialogue(team, monkeypatch)
    asset = audio_result(audio_job, tmp_path)
    before = team['a'].get('/api/projects/' + team['pid'] + '/jobs').json()
    response = submit_video(team, model, batch=batch)
    assert response.status_code == 400 and '明确采纳' in response.text, response.text
    assert team['a'].get('/api/projects/' + team['pid'] + '/jobs').json() == before
    adopted = team['a'].post(candidate(team, audio_job) + '/adopt', json=version(row))
    assert adopted.status_code == 200, adopted.text
    current = adopted.json()['target']
    assert submit_video(team, model, batch=batch, actor=team['b']).status_code == 403
    assert submit_video(team, model, batch=batch, actor=team['viewer']).status_code == 403
    response = submit_video(team, model, batch=batch, extra={
        'dialogue_audio': [{'assetId': 'forged-other-production'}],
        'dialogue_audio_asset_ids': ['forged-other-production'],
    })
    assert response.status_code == 200, response.text
    job = team['a'].get('/api/jobs/' + response.json()['job_ids'][0]).json() if batch else response.json()
    assert job['input']['dialogue_audio_asset_ids'] == [asset['id']]
    assert job['input']['dialogue_audio_mode'] == 'seedance_reference'
    assert job['input']['parameters']['generate_audio'] is True
    assert 'signature=' not in json.dumps(job['input'])
    video = tmp_path / 'mock-result.mp4'
    completed = subprocess.run([ffmpeg_executable(), '-v', 'error', '-f', 'lavfi', '-i',
        'color=c=blue:s=64x64:r=24:d=4', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)],
        capture_output=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    calls = []
    def handle(request):
        calls.append((request.method, request.url.path))
        if request.url.path == '/mock-result.mp4':
            assert 'authorization' not in request.headers
            return httpx.Response(200, content=video.read_bytes())
        if request.method == 'POST':
            body = json.loads(request.content)
            assert body['generate_audio'] is True
            assert body['omni_reference_task_type'] == 'reference'
            assert body['duration'] == 4
            assert '@音频1' in body['content'][0]['text']
            item = body['content'][-1]
            assert item['role'] == 'reference_audio' and item['type'] == 'audio_url'
            parsed = urlsplit(item['audio_url']['url'])
            assert parsed.scheme == 'https' and parsed.netloc == 'studio.example'
            aid = parsed.path.rsplit('/', 1)[-1]
            query = parse_qs(parsed.query)
            assert valid_signature(aid, int(query['expires'][0]), query['signature'][0], 'GET', query['purpose'][0])
            with s.db() as c:
                derived = c.execute('SELECT * FROM assets WHERE id=%s', (aid,)).fetchone()
            assert derived['source'] == 'derived' and derived['production_id'] == team['production']
            metadata = json.loads(derived['metadata'])
            assert 3.9 <= metadata['duration'] <= 4.2
            assert 'signature=' not in json.dumps(metadata)
            return httpx.Response(200, json={'id': 'mock-hc-task'})
        return httpx.Response(200, json={'status': 'succeeded', 'content': {'video_url': 'https://media.example/mock-result.mp4'}})
    mock_egress(monkeypatch, handle)
    assert s.job_update(job['id'], status='running')
    result = Worker().execute(job)
    assert result['assets'][0]['kind'] == 'video'
    assert calls == [('POST', '/v3/video/tasks'), ('GET', '/v3/video/tasks/mock-hc-task'), ('GET', '/mock-result.mp4')]
    assert team['a'].get(url(team, row)).json() == current  # no automatic writeback
    with s.db() as c:
        resumed = s.unpack(c.execute('SELECT * FROM jobs WHERE id=%s', (job['id'],)).fetchone())
        count = c.execute("SELECT count(*) n FROM assets WHERE project_id=%s AND source='derived'", (team['pid'],)).fetchone()['n']
    calls.clear()
    Worker().execute(resumed)
    assert calls == [('GET', '/v3/video/tasks/mock-hc-task'), ('GET', '/mock-result.mp4')]
    with s.db() as c:
        assert c.execute("SELECT count(*) n FROM assets WHERE project_id=%s AND source='derived'", (team['pid'],)).fetchone()['n'] == count
    assert s.job_update(job['id'], status='succeeded', result=result)
    assert team['a'].get(url(team, row)).json() == current
    adopted_video = team['a'].post(candidate(team, job) + '/adopt', json=version(current))
    assert adopted_video.status_code == 200, adopted_video.text
    node = adopted_video.json()['target']['content']['nodes'][0]['data']
    assert node['assetId'] == result['assets'][0]['id'] and node['stale'] is False


def test_missing_public_route_fails_before_admission(team, monkeypatch, tmp_path):
    row, model, audio_job = setup_dialogue(team, monkeypatch, public=False)
    audio_result(audio_job, tmp_path)
    assert team['a'].post(candidate(team, audio_job) + '/adopt', json=version(row)).status_code == 200
    for batch in (False, True):
        response = submit_video(team, model, batch=batch)
        assert response.status_code == 400 and '公网访问地址' in response.text, response.text


def test_unpublished_audio_capability_keeps_hc_legacy_behavior(team, monkeypatch):
    _, model, _ = setup_dialogue(team, monkeypatch, public=False, capability=False)
    response = submit_video(team, model)
    assert response.status_code == 200, response.text
    assert not response.json()['input'].get('dialogue_audio')


def test_unlinked_caller_audio_is_not_an_adopted_dialogue():
    from backend.video_dialogue import bind_fixed_dialogue_audio
    with pytest.raises(ValueError, match='已采纳'):
        bind_fixed_dialogue_audio({}, 'unlinked', 'video', {'dialogue_audio': [{'assetId': 'forged'}]}, [], require_canonical=True)


@pytest.mark.parametrize('model,duration,track_duration', [
    ('doubao-seedance-2.0', 20, 18), ('doubao-seedance-2.5', 31, 29),
    ('doubao-seedance-2.5', 4, 5),
])
def test_dialogue_is_never_silently_truncated(model, duration, track_duration):
    provider = {'models': {'video': model}, 'capabilities': {'audio_reference': True}}
    with pytest.raises(ValueError, match='超过'):
        hc_atom.validate_fixed_dialogue(provider,
            {'dialogue_audio_mode': 'seedance_reference', 'dialogue_audio': [{'start': 0.3, 'duration': track_duration}]},
            {'duration': duration, 'generate_audio': True})


@pytest.mark.parametrize('model', ['doubao-seedance-2.0', 'dreamina-seedance-2.5'])
def test_image_and_dialogue_use_reference_roles_and_explicit_ratio(monkeypatch, model):
    from tests.test_hc_atom import stored_job, provider
    from backend.providers import volcengine_ark
    configured = provider()
    configured.update(public_base_url='https://studio.example', capabilities={'audio_reference': True})
    configured['models']['video'] = model
    job = stored_job('video', configured)
    job['input'].update(prompt='说话', ratio='9:16', dialogue_audio_mode='seedance_reference',
                        dialogue_audio=[{'assetId': 'track', 'duration': 1, 'start': 0.3}])
    # Protocol combination only. Real mix/signing/download/adoption is covered above.
    monkeypatch.setattr(volcengine_ark, '_dialogue_reference_audio', lambda *args, **kwargs: 'https://studio.example/signed-audio')
    monkeypatch.setattr(hc_atom, '_register_seedance_asset', lambda *args: 'asset://reviewed-image')
    monkeypatch.setattr(hc_atom, '_wait_seedance_v3', lambda *args: {'mock': True})
    bodies = []
    def handle(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={'id': 'mock-reference-task'})
    mock_egress(monkeypatch, handle)
    hc_atom._generate_seedance_v3(Worker(), job, configured, model, [{'id': 'frame'}],
                                 {'duration': 4, 'generate_audio': True})
    assert len(bodies) == 1
    body = bodies[0]
    assert body['ratio'] == '9:16'
    assert [item.get('role') for item in body['content']] == [None, 'reference_image', 'reference_audio']
    assert '@图片1' in body['content'][0]['text'] and '@音频1' in body['content'][0]['text']
    assert ('omni_reference_task_type' in body) == ('2.5' in model)
