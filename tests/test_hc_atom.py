import json
import time
import uuid

import httpx

from tests.platform_model_helpers import bind_adapter_job
from tests.egress_helpers import mock_egress
from backend import store as s
from backend import worker as worker_module
from backend.providers import common, hc_atom
from backend.worker import Worker

s.init()


class NoWait:
    def wait(self, seconds):
        return False

    def is_set(self):
        return False


def provider():
    return {
        'id': 'hc', 'name': '幻场 AI', 'type': 'hc_atom', 'local': False,
        'url': 'https://ai.example', 'api_key': 'yh-secret',
        'models': {'text': 'qwen-text', 'image': 'flux-image', 'video': 'kling-video'},
        'parameters': {'image': {'size': '1024x1024'}, 'video': {'duration': 5, 'ratio': '16:9'}},
    }


def test_explicit_gateway_is_never_silently_redirected():
    configured = provider()
    configured['url'] = hc_atom.LEGACY_BASE_URL
    assert hc_atom._root(configured) == hc_atom.LEGACY_BASE_URL


def test_http_200_business_error_is_not_treated_as_created_task(monkeypatch):
    configured = provider()
    configured['models']['video'] = 'doubao-seedance-2.5'
    item = stored_job('video', configured)
    item['input'].update({'model': 'doubao-seedance-2.5', 'parameters': {'duration': 4}})
    original = httpx.Client

    def handle(request):
        return httpx.Response(200, json={'code': 500, 'msg': '当前用户未分配该模型可用的厂商', 'data': None})

    mock_egress(monkeypatch,handle)
    worker = Worker()
    worker.halt = NoWait()
    try:
        hc_atom.generate_video(worker, item, configured)
        assert False, 'business errors must fail before polling'
    except ValueError as exc:
        assert str(exc) == '幻场 AI 返回业务错误：当前用户未分配该模型可用的厂商'


def stored_job(kind, provider_value, provider_job_id=None):
    pid = 'hc-project-' + uuid.uuid4().hex
    jid = 'hc-job-' + uuid.uuid4().hex
    now = time.time()
    inp = {'provider': provider_value['id'], 'prompt': '电影感镜头'}
    with s.db() as db:
        db.execute(
            'INSERT INTO projects(id,name,revision,document,created,updated) VALUES(%s,%s,1,%s,%s,%s)',
            (pid, 'HC test', '{}', now, now),
        )
        db.execute(
            'INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,provider_job_id,created,updated) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (jid, 'hc-submit-' + uuid.uuid4().hex, pid, 'node', kind, 'running', s.dumps(inp), provider_job_id, now, now),
        )
        bind_adapter_job(db,jid,kind,provider_value,inp)
    return {'id': jid, 'submission_id': 'hc-submit-test', 'project_id': pid, 'node_id': 'node', 'kind': kind, 'status': 'running', 'input': inp, 'provider_job_id': provider_job_id}


def test_catalog_is_read_only_and_classifies_unified_models(monkeypatch):
    original = httpx.Client

    def handle(request):
        assert request.method == 'GET'
        assert request.url.path == '/v1/models'
        assert request.headers['authorization'] == 'Bearer yh-secret'
        return httpx.Response(200, json={'data': [
            {'id': 'qwen-text'}, {'id': 'flux-image'}, {'id': 'kling-video'}, {'id': 'embedding-v1'},
            {'id': 'wan2.7-i2v'}, {'id': 'happyhorse-1.1-r2v'}, {'id': 'MiniMax-H3'},
            {'id': 'wan2.5-i2i-preview'}, {'id': 'tencent-mps-superres'},
        ]})

    mock_egress(monkeypatch,handle)
    models = hc_atom.list_models(provider())
    classified = {row['id']: row['kind'] for row in models}
    assert classified == {
        'flux-image': 'image', 'happyhorse-1.1-r2v': 'video', 'kling-video': 'video',
        'MiniMax-H3': 'video', 'qwen-text': 'text', 'wan2.7-i2v': 'video',
        'wan2.5-i2i-preview': 'image',
    }


def test_text_reuses_openai_compatible_streaming_endpoint(monkeypatch):
    item = stored_job('text', provider())
    original = httpx.Client

    def handle(request):
        assert request.url.path == '/v1/chat/completions'
        body = json.loads(request.read())
        assert body['model'] == 'qwen-text'
        return httpx.Response(200, content=b'data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n')

    mock_egress(monkeypatch,handle)
    assert Worker().execute(item) == {'text': 'OK'}


def test_video_submit_poll_and_download(monkeypatch):
    item = stored_job('video', provider())
    calls = []
    original = httpx.Client

    def handle(request):
        calls.append((request.method, request.url.path))
        if request.method == 'POST':
            body = json.loads(request.read())
            assert body['model'] == 'kling-video' and body['duration'] == 5
            assert request.headers['idempotency-key'] == item['submission_id']
            return httpx.Response(200, json={'code': 200, 'data': {'taskId': 'vg-1', 'status': 'PENDING'}})
        return httpx.Response(200, json={'code': 200, 'data': {'taskId': 'vg-1', 'status': 'SUCCESS', 'progress': 100, 'resultUrl': 'https://result.example/video.mp4'}})

    mock_egress(monkeypatch,handle)
    monkeypatch.setattr(common, 'download_result', lambda job, url, ext, recoverable=False: {'id': 'video-asset', 'kind': 'video'})
    worker = Worker()
    worker.halt = NoWait()
    assert hc_atom.generate_video(worker, item, provider())['assets'][0]['id'] == 'video-asset'
    assert calls == [('POST', '/video/generation/tasks'), ('GET', '/video/generation/tasks/vg-1')]


def test_seedance_uses_v3_signed_first_frame_and_minimum_duration(monkeypatch):
    configured = provider()
    configured['id'] = 'hc-assets-' + uuid.uuid4().hex
    configured['models']['video'] = 'doubao-seedance-2.5'
    configured['public_base_url'] = 'https://studio.example'
    item = stored_job('video', configured)
    item['input'].update({
        'model': 'doubao-seedance-2.5', 'parameters': {'duration': 3, 'resolution': '480p'},
        'ratio': '16:9',
    })
    aid = 'hc-frame-' + uuid.uuid4().hex
    path = s.ASSETS / (aid + '.png')
    path.write_bytes(b'png-test')
    with s.db() as db:
        db.execute(
            'INSERT INTO assets(id,project_id,name,kind,path,mime,metadata,created) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
            (aid, item['project_id'], 'frame.png', 'image', path.name, 'image/png', '{}', time.time()),
        )
    item['input']['asset_ids'] = [aid]
    original = httpx.Client
    calls = []

    def handle(request):
        calls.append((request.method, request.url.path))
        if request.url.path == '/v3/asset-groups':
            body = json.loads(request.read())
            assert body['name'] == '安影 Seedance 虚拟人物素材'
            return httpx.Response(200, json={'code': 200, 'data': {'groupId': 'group-1'}})
        if request.url.path == '/v3/assets':
            body = json.loads(request.read())
            assert request.headers['group_id'] == 'group-1'
            assert body['assetType'] == 'Image'
            assert body['url'].startswith(f'https://studio.example/api/provider-assets/{aid}?expires=')
            assert 'signature=' in body['url']
            return httpx.Response(200, json={'code': 200, 'data': {'id': 'asset-1', 'status': 'Processing'}})
        if request.url.path == '/v3/assets/detail':
            assert request.headers['group_id'] == 'group-1'
            assert json.loads(request.read()) == {'assetId': 'asset-1'}
            return httpx.Response(200, json={'code': 200, 'data': {'id': 'asset-1', 'status': 'Active'}})
        if request.url.path == '/v3/video/tasks' and request.method == 'POST':
            body = json.loads(request.read())
            assert body['model'] == 'doubao-seedance-2.5'
            assert body['duration'] == 4 and body['ratio'] == 'adaptive'
            assert body['resolution'] == '480p'
            assert body['content'][0] == {'type': 'text', 'text': '电影感镜头'}
            image = body['content'][1]
            assert image['type'] == 'image_url' and image['role'] == 'first_frame'
            assert image['image_url']['url'] == 'asset://asset-1'
            return httpx.Response(200, json={'id': 'cgt-1', 'status': 'queued'})
        assert request.url.path == '/v3/video/tasks/cgt-1'
        return httpx.Response(200, json={
            'id': 'cgt-1', 'status': 'succeeded',
            'content': {'video_url': 'https://result.example/video.mp4'},
        })

    mock_egress(monkeypatch,handle)
    monkeypatch.setattr(common, 'download_result', lambda job, url, ext, recoverable=False: {'id': 'v3-video', 'kind': 'video'})
    worker = Worker()
    worker.halt = NoWait()
    assert hc_atom.generate_video(worker, item, configured)['assets'][0]['id'] == 'v3-video'
    assert calls == [
        ('POST', '/v3/asset-groups'),
        ('POST', '/v3/assets'),
        ('POST', '/v3/assets/detail'),
        ('POST', '/v3/video/tasks'),
        ('GET', '/v3/video/tasks/cgt-1'),
    ]

    # A retry/re-generation with the same local image reuses the reviewed remote
    # asset and does not create or review a duplicate asset.
    def reject_network(request):
        raise AssertionError('active provider asset should be served from the local mapping cache')

    cached_client = original(transport=httpx.MockTransport(reject_network))
    with s.db() as db:
        local_asset = dict(db.execute('SELECT * FROM assets WHERE id=%s', (aid,)).fetchone())
    assert hc_atom._register_seedance_asset(worker, item, cached_client, configured, local_asset) == 'asset://asset-1'


def test_seedance_stops_before_video_submit_when_provider_asset_review_fails(monkeypatch):
    configured = provider()
    configured['id'] = 'hc-assets-failed-' + uuid.uuid4().hex
    configured['models']['video'] = 'doubao-seedance-2.5'
    configured['public_base_url'] = 'https://studio.example'
    item = stored_job('video', configured)
    item['input'].update({'model': 'doubao-seedance-2.5', 'parameters': {'duration': 4}})
    aid = 'hc-sensitive-frame-' + uuid.uuid4().hex
    path = s.ASSETS / (aid + '.png')
    path.write_bytes(b'png-test')
    with s.db() as db:
        db.execute(
            'INSERT INTO assets(id,project_id,name,kind,path,mime,metadata,created) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
            (aid, item['project_id'], 'sensitive.png', 'image', path.name, 'image/png', '{}', time.time()),
        )
    item['input']['asset_ids'] = [aid]
    original = httpx.Client
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.url.path == '/v3/asset-groups':
            return httpx.Response(200, json={'code': 200, 'data': {'groupId': 'group-sensitive'}})
        if request.url.path == '/v3/assets':
            return httpx.Response(200, json={'code': 200, 'data': {'id': 'asset-sensitive', 'status': 'Processing'}})
        if request.url.path == '/v3/assets/detail':
            return httpx.Response(200, json={'code': 200, 'data': {
                'id': 'asset-sensitive', 'status': 'Failed', 'failReason': '检测到真人隐私信息',
            }})
        raise AssertionError('video task must not be submitted before the provider asset is active')

    mock_egress(monkeypatch,handle)
    worker = Worker()
    worker.halt = NoWait()
    try:
        hc_atom.generate_video(worker, item, configured)
        assert False, 'failed provider asset review must block video submission'
    except ValueError as exc:
        assert str(exc) == '幻场虚拟人像素材审核失败：检测到真人隐私信息'
    assert calls == ['/v3/asset-groups', '/v3/assets', '/v3/assets/detail']


def test_seedance_retries_transport_reset_with_same_idempotency_key(monkeypatch):
    configured = provider()
    configured['models']['video'] = 'doubao-seedance-2.5'
    item = stored_job('video', configured)
    item['input'].update({'model': 'doubao-seedance-2.5', 'parameters': {'duration': 4}})
    original = httpx.Client
    posts = []

    def handle(request):
        if request.method == 'POST':
            posts.append(request.headers['idempotency-key'])
            if len(posts) == 1:
                raise httpx.ReadError('reset', request=request)
            return httpx.Response(200, json={'id': 'cgt-retry'})
        return httpx.Response(200, json={
            'id': 'cgt-retry', 'status': 'succeeded',
            'content': {'video_url': 'https://result.example/video.mp4'},
        })

    mock_egress(monkeypatch,handle)
    monkeypatch.setattr(common, 'download_result', lambda *args, **kwargs: {'id': 'retry-video'})
    worker = Worker()
    worker.halt = NoWait()
    assert hc_atom.generate_video(worker, item, configured)['assets'][0]['id'] == 'retry-video'
    assert posts == [item['submission_id'], item['submission_id']]


def test_reference_image_uses_async_task_protocol(monkeypatch):
    item = stored_job('image', provider())
    aid = 'hc-ref-' + uuid.uuid4().hex
    path = s.ASSETS / (aid + '.png')
    path.write_bytes(b'png-test')
    with s.db() as db:
        db.execute(
            'INSERT INTO assets(id,project_id,name,kind,path,mime,metadata,created) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
            (aid, item['project_id'], 'reference.png', 'image', path.name, 'image/png', '{}', time.time()),
        )
    item['input']['asset_ids'] = [aid]
    original = httpx.Client

    def handle(request):
        if request.method == 'POST':
            body = json.loads(request.read())
            assert body['input']['images'][0].startswith('data:image/png;base64,')
            return httpx.Response(200, json={'code': 200, 'data': {'taskId': 'ig-1'}})
        return httpx.Response(200, json={'code': 200, 'data': {'status': 'SUCCESS', 'resultUrls': ['https://result.example/image.png']}})

    mock_egress(monkeypatch,handle)
    monkeypatch.setattr(common, 'download_result', lambda job, url, ext, recoverable=False: {'id': 'image-asset', 'kind': 'image'})
    worker = Worker()
    worker.halt = NoWait()
    assert hc_atom.generate_image(worker, item, provider())['assets'][0]['id'] == 'image-asset'
