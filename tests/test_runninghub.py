import json
import time
import uuid

import httpx
from PIL import Image

from backend import store as s
from backend import worker as worker_module
from backend.providers import common, runninghub
from backend.worker import Worker

s.init()


class NoWait:
    def wait(self, seconds):
        return False

    def is_set(self):
        return False


def provider():
    return {
        'id': 'rh', 'name': 'RunningHub', 'type': 'runninghub', 'local': False,
        'url': 'https://www.runninghub.ai', 'api_key': 'rh-secret',
        'models': {
            'text': 'bytedance/doubao-seed-2.1-pro',
            'image': 'seedream-v5-pro',
            'video': 'bytedance/seedance-2.5-token',
        },
        'parameters': {'image': {'resolution': '2k'}, 'video': {'duration': 5, 'resolution': '720p'}},
    }


def stored_job(kind, provider_value, provider_job_id=None):
    pid = 'rh-project-' + uuid.uuid4().hex
    jid = 'rh-job-' + uuid.uuid4().hex
    now = time.time()
    inp = {'provider': provider_value['id'], 'prompt': '电影感镜头'}
    with s.db() as db:
        db.execute(
            'INSERT INTO projects(id,name,revision,document,created,updated) VALUES(%s,%s,1,%s,%s,%s)',
            (pid, 'RunningHub test', '{}', now, now),
        )
        db.execute(
            'INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,provider_job_id,created,updated) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (jid, 'rh-submit-' + uuid.uuid4().hex, pid, 'node', kind, 'running', s.dumps(inp), provider_job_id, now, now),
        )
        db.execute('INSERT INTO job_private VALUES(%s,%s)', (jid, s.dumps(provider_value)))
    return {'id': jid, 'submission_id': 'rh-submit-test', 'project_id': pid, 'node_id': 'node', 'kind': kind, 'status': 'running', 'input': inp, 'provider_job_id': provider_job_id}


def add_image(item, name='reference.png'):
    aid = 'rh-ref-' + uuid.uuid4().hex
    path = s.ASSETS / (aid + '.png')
    Image.new('RGB', (16, 9), 'red').save(path)
    with s.db() as db:
        db.execute(
            'INSERT INTO assets(id,project_id,name,kind,path,mime,metadata,created) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
            (aid, item['project_id'], name, 'image', path.name, 'image/png', '{}', time.time()),
        )
    return aid


def test_verify_reads_account_and_public_model_catalog(monkeypatch):
    original = httpx.Client

    def handle(request):
        if request.url.path == '/uc/openapi/accountStatus':
            assert request.headers['authorization'] == 'Bearer rh-secret'
            return httpx.Response(200, json={'code': 0, 'msg': 'success', 'data': {'apiType': 'ENTERPRISE_SHARED'}})
        assert request.url.path == '/llm/api/models'
        return httpx.Response(200, json={'data': [{'modelKey': 'qwen/qwen3.8-max', 'displayName': 'Qwen 3.8 Max', 'capabilities': {'chat': True}}]})

    monkeypatch.setattr(runninghub.httpx, 'Client', lambda **kw: original(**kw, transport=httpx.MockTransport(handle)))
    result = runninghub.verify(provider())
    assert result['api_type'] == 'ENTERPRISE_SHARED'
    assert {row['kind'] for row in result['models']} == {'text', 'image', 'video'}


def test_text_reuses_runninghub_openai_stream(monkeypatch):
    item = stored_job('text', provider())
    original = httpx.Client

    def handle(request):
        assert str(request.url).startswith('https://llm.runninghub.ai/v1/chat/completions')
        assert json.loads(request.read())['model'] == 'bytedance/doubao-seed-2.1-pro'
        return httpx.Response(200, content=b'data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n')

    monkeypatch.setattr(worker_module.httpx, 'Client', lambda **kw: original(**kw, transport=httpx.MockTransport(handle)))
    assert Worker().execute(item) == {'text': 'OK'}


def test_image_reference_upload_submit_poll_and_download(monkeypatch):
    item = stored_job('image', provider())
    item['input']['asset_ids'] = [add_image(item)]
    paths = []
    original = httpx.Client

    def handle(request):
        paths.append(request.url.path)
        if request.url.path.endswith('/media/upload/binary'):
            assert request.headers['content-type'].startswith('multipart/form-data; boundary=')
            return httpx.Response(200, json={'code': 0, 'data': {'download_url': 'https://input.example/reference.png'}})
        if request.url.path.endswith('/image-to-image'):
            body = json.loads(request.read())
            assert body['imageUrls'] == ['https://input.example/reference.png']
            return httpx.Response(200, json={'taskId': 'image-task', 'status': 'RUNNING'})
        return httpx.Response(200, json={'taskId': 'image-task', 'status': 'SUCCESS', 'results': [{'fileUrl': 'https://result.example/result.png'}]})

    monkeypatch.setattr(runninghub.httpx, 'Client', lambda **kw: original(**kw, transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(common, 'download_result', lambda job, url, ext, recoverable=False: {'id': 'image-asset', 'kind': 'image'})
    worker = Worker(); worker.halt = NoWait()
    assert runninghub.generate_image(worker, item, provider())['assets'][0]['id'] == 'image-asset'
    assert paths == ['/openapi/v2/media/upload/binary', '/openapi/v2/seedream-v5-pro/image-to-image', '/openapi/v2/query']


def test_video_selects_text_first_frame_and_multireference_endpoints(monkeypatch):
    original = httpx.Client
    cases = [(0, '/text-to-video'), (1, '/image-to-video'), (2, '/multimodal-video')]
    for count, suffix in cases:
        item = stored_job('video', provider())
        item['input']['asset_ids'] = [add_image(item, str(index) + '.png') for index in range(count)]
        submitted = []

        def handle(request):
            if request.url.path.endswith('/media/upload/binary'):
                return httpx.Response(200, json={'code': 0, 'data': {'download_url': 'https://input.example/reference.png'}})
            if request.url.path.endswith('/query'):
                return httpx.Response(200, json={'taskId': 'video-task', 'status': 'SUCCESS', 'results': [{'url': 'https://result.example/result.mp4'}]})
            submitted.append(request.url.path)
            return httpx.Response(200, json={'taskId': 'video-task', 'status': 'RUNNING'})

        monkeypatch.setattr(runninghub.httpx, 'Client', lambda **kw: original(**kw, transport=httpx.MockTransport(handle)))
        monkeypatch.setattr(common, 'download_result', lambda job, url, ext, recoverable=False: {'id': 'video-asset', 'kind': 'video'})
        worker = Worker(); worker.halt = NoWait()
        assert runninghub.generate_video(worker, item, provider())['assets'][0]['id'] == 'video-asset'
        assert submitted[0].endswith(suffix)
