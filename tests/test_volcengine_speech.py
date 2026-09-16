from tests.egress_helpers import mock_egress
import base64
import json
import time

import httpx

from backend import store as s
from backend.providers import common, volcengine_speech


class WorkerStub:
    def __init__(self):
        self.phases = []

    def progress(self, _job, phase, _percent=None):
        self.phases.append(phase)

    def cancelled(self, _job):
        return False


def test_speech_v3_sse_uses_fixed_voice_and_registers_dialogue(monkeypatch):
    s.init()
    now = time.time()
    production_id = s.uid('production-')
    project_id = s.uid('project-')
    job_id = s.uid('job-')
    job_input = {
        'prompt': '山门到了。',
        'voice_type': 'zh_female_vv_uranus_bigtts',
        'voice_version': 3,
        'character_name': '糯糯',
        'output_name': '糯糯试听.wav',
        'parameters': {
            'format': 'mp3', 'sample_rate': 24000, 'speech_rate': 8,
            'emotion': '克制的喜悦',
            'context_texts': ['影片对白表演指令。全镜情绪：久别重逢；本句表演：克制的喜悦。'],
        },
        'dialogue': {'id': 'dialogue-1', 'shotUid': 'shot-uid-1', 'voiceVersion': 3},
    }
    with s.db() as connection:
        connection.execute(
            'INSERT INTO productions(id,name,created,updated) VALUES(%s,%s,%s,%s)',
            (production_id, '语音测试', now, now),
        )
        connection.execute(
            'INSERT INTO projects(id,name,revision,document,created,updated,production_id,episode_no,episode_title) VALUES(%s,%s,1,%s,%s,%s,%s,1,%s)',
            (project_id, '第一集', '{}', now, now, production_id, '第一集'),
        )
        connection.execute(
            'INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated,production_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (job_id, job_id, project_id, 'dialogue:1', 'audio', 'running', s.dumps(job_input), now, now, production_id),
        )

    captured = {}

    def respond(request):
        captured['headers'] = dict(request.headers)
        captured['body'] = json.loads(request.content)
        payload = base64.b64encode(b'fake-mp3').decode()
        stream = f'data: {json.dumps({"code": 0, "data": payload})}\n\ndata: {json.dumps({"code": 20000000})}\n\n'
        return httpx.Response(200, text=stream)

    original = httpx.Client
    mock_egress(monkeypatch,respond)
    monkeypatch.setattr(common, 'probe', lambda _path: {'duration': 1.25, 'has_audio': True})
    worker = WorkerStub()
    job = {'id': job_id, 'project_id': project_id, 'node_id': 'dialogue:1', 'input': job_input}
    result = volcengine_speech.synthesize(
        worker,
        job,
        {'url':'https://openspeech.bytedance.com','api_key': 'speech-key', 'resource_id': 'seed-tts-2.0'},
    )

    assert captured['headers']['x-api-key'] == 'speech-key'
    assert captured['headers']['x-api-resource-id'] == 'seed-tts-2.0'
    assert captured['body']['req_params']['speaker'] == job_input['voice_type']
    assert captured['body']['req_params']['audio_params']['speech_rate'] == 8
    additions = json.loads(captured['body']['req_params']['additions'])
    assert additions['context_texts'] == job_input['parameters']['context_texts']
    assert 'emotion' not in additions and 'enable_emotion' not in additions
    assert result['assets'][0]['kind'] == 'audio'
    assert result['assets'][0]['name'].endswith('.mp3')
    with s.db() as connection:
        asset = s.unpack(connection.execute('SELECT * FROM assets WHERE id=%s', (result['assets'][0]['id'],)).fetchone())
    assert asset['metadata']['input']['dialogue']['shotUid'] == 'shot-uid-1'
    assert asset['metadata']['duration'] == 1.25


def test_speech_verify_does_not_make_a_paid_request():
    result = volcengine_speech.verify({'api_key': 'configured', 'resource_id': 'seed-tts-2.0'})
    assert result['status'] == 'configured'
