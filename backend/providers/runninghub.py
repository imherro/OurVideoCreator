"""RunningHub unified LLM, image, and asynchronous video provider."""
from __future__ import annotations

import mimetypes
from pathlib import Path

import httpx

from .. import store as s
from .. import provider_egress
from . import common


DEFAULT_BASE_URL = 'https://www.runninghub.ai'
DEFAULT_IMAGE_MODEL = 'seedream-v5-pro'
DEFAULT_VIDEO_MODEL = 'bytedance/seedance-2.5-token'
KINDS = ('text', 'image', 'video')


def _root(provider):
    return str(provider.get('url') or DEFAULT_BASE_URL).rstrip('/').removesuffix('/openapi/v2')


def text_base_url(provider):
    # Text and media hosts require separate explicit platform Provider configs.
    # Never silently move a frozen account to another origin.
    return str(provider['url']).rstrip('/')


def _headers(provider, content_type=True):
    key = str(provider.get('api_key') or '').strip()
    if not key:
        raise ValueError('RunningHub 尚未配置 API Key')
    headers = {'Authorization': 'Bearer ' + key}
    if content_type:
        headers['Content-Type'] = 'application/json'
    return headers


def model_for(provider, kind):
    kind = 'text' if kind == 'storyboard' else kind
    return str((provider.get('models') or {}).get(kind) or provider.get('model') or '').strip()


def _media_models():
    return [
        {
            'id': DEFAULT_IMAGE_MODEL,
            'name': 'Seedream 5 Pro（自动文生图 / 最多 10 图参考）',
            'kind': 'image',
            'capabilities': {'image_reference': True, 'max_references': 10, 'end_frame': False},
        },
        {
            'id': DEFAULT_VIDEO_MODEL,
            'name': 'Seedance 2.5 Token（自动文生 / 首帧 / 首尾帧 / 多参考）',
            'kind': 'video',
            'capabilities': {'image_reference': True, 'max_references': 30, 'end_frame': True},
        },
        {
            'id': 'bytedance/seedance-2.5-global-token',
            'name': 'Seedance 2.5 Global Token（自动选择生成模式）',
            'kind': 'video',
            'capabilities': {'image_reference': True, 'max_references': 30, 'end_frame': True},
        },
    ]


def list_models(provider):
    """Read RunningHub's public LLM catalogue and add supported media profiles."""
    try:
        with provider_egress.client(origin=provider['url'],timeout=30, trust_env=True) as client:
            response = client.get(_root(provider) + '/llm/api/models')
            response.raise_for_status()
            value = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ValueError('RunningHub 模型目录读取失败，请检查网络和服务地址') from exc
    rows = value.get('data') if isinstance(value, dict) else value
    if not isinstance(rows, list):
        raise ValueError('RunningHub 文本模型目录返回格式不正确')
    models = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get('modelKey') or item.get('publicName') or item.get('id') or '').strip()
        capabilities = item.get('capabilities') if isinstance(item.get('capabilities'), dict) else {}
        if not model_id or capabilities.get('chat') is False:
            continue
        models.append({
            'id': model_id,
            'name': str(item.get('displayName') or item.get('publicName') or model_id),
            'kind': 'text',
            'capabilities': {'image_reference': False, 'max_references': None, 'end_frame': False},
        })
    models.extend(_media_models())
    configured = provider.get('models') if isinstance(provider.get('models'), dict) else {}
    return sorted(models, key=lambda row: (row['id'] != configured.get(row['kind']), row['name']))


def verify(provider):
    key = str(provider.get('api_key') or '').strip()
    try:
        with provider_egress.client(origin=provider['url'],timeout=30, headers=_headers(provider), trust_env=True) as client:
            value = common.checked(client.post(_root(provider) + '/uc/openapi/accountStatus', json={'apikey': key}))
    except httpx.HTTPError as exc:
        raise ValueError('RunningHub 连接失败，请检查网络、服务地址和代理设置') from exc
    if value.get('code') not in (0, 200):
        raise ValueError(str(value.get('msg') or value.get('message') or 'RunningHub API Key 验证失败'))
    data = value.get('data') if isinstance(value.get('data'), dict) else {}
    models = list_models(provider)
    counts = {kind: sum(model['kind'] == kind for model in models) for kind in KINDS}
    return {
        'status': 'ready',
        'message': f'RunningHub API Key 鉴权通过（{data.get("apiType") or "类型未知"}），读取到 {len(models)} 个适用模型',
        'api_type': data.get('apiType'),
        'models': models,
        'counts': counts,
    }


def check_configured_model(provider, kind):
    if kind not in KINDS:
        raise ValueError('RunningHub 模型用途无效')
    target = model_for(provider, kind)
    if not target:
        raise ValueError(f'请先选择 RunningHub {kind} 模型')
    found = next((row for row in list_models(provider) if row['kind'] == kind and row['id'] == target), None)
    return {
        'status': 'listed' if found else 'unlisted',
        'kind': kind,
        'model': target,
        'message': '模型已在 RunningHub 目录中。' if found else '当前适配器尚未收录该媒体端点；请使用目录内的模型。',
    }


def model_capabilities(provider, kind, model_id=None):
    target = str(model_id or model_for(provider, kind)).strip()
    found = next((row for row in _media_models() if row['kind'] == kind and row['id'] == target), None)
    return found['capabilities'] if found else {'image_reference': False, 'max_references': None, 'end_frame': False}


def _asset_path(asset):
    path = (s.ASSETS / str(asset.get('path') or '')).resolve()
    if not path.is_relative_to(s.ASSETS) or not path.is_file():
        raise ValueError('RunningHub 参考素材文件已丢失')
    return path


def _upload(client, root, asset):
    path = _asset_path(asset)
    mime = str(asset.get('mime') or mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
    with path.open('rb') as handle:
        response = client.post(
            root + '/openapi/v2/media/upload/binary',
            headers={'Authorization': client.headers['Authorization']},
            files={'file': (path.name, handle, mime)},
        )
    value = common.checked(response)
    if value.get('code') not in (0, 200):
        raise ValueError(str(value.get('msg') or value.get('message') or 'RunningHub 素材上传失败'))
    data = value.get('data') if isinstance(value.get('data'), dict) else {}
    url = data.get('download_url') or data.get('downloadUrl')
    if not url:
        raise ValueError('RunningHub 素材上传成功，但未返回下载地址')
    provider_egress.validate_url(url,resolve=True)
    return url


def _result_urls(value):
    urls = []
    def walk(item):
        if isinstance(item, str):
            lowered = item.split('?', 1)[0].lower()
            if item.startswith(('http://', 'https://')) and lowered.endswith(('.png', '.jpg', '.jpeg', '.webp', '.mp4', '.mov')):
                urls.append(item)
        elif isinstance(item, list):
            for child in item:
                walk(child)
        elif isinstance(item, dict):
            for key, child in item.items():
                if key.lower() in ('fileurl', 'url', 'download_url', 'downloadurl', 'results', 'data', 'output'):
                    walk(child)
    walk(value.get('results') if isinstance(value, dict) else value)
    return list(dict.fromkeys(urls))


def _wait_task(worker, job, client, root, task_id, kind):
    query_url = root + '/openapi/v2/query'
    while not worker.halt.wait(4):
        if worker.cancelled(job):
            raise InterruptedError()
        value = common.checked(client.post(query_url, json={'taskId': str(task_id)}), recoverable=True)
        status = str(value.get('status') or '').upper()
        worker.progress(job, f'RunningHub {"生成图片" if kind == "image" else "生成视频"}')
        if status in ('FAILED', 'ERROR', 'CANCELLED'):
            raise ValueError(str(value.get('errorMessage') or value.get('message') or 'RunningHub 生成失败'))
        if status in ('SUCCESS', 'SUCCEEDED', 'COMPLETED'):
            urls = _result_urls(value)
            if not urls:
                raise ValueError('RunningHub 任务成功，但没有返回媒体地址')
            expected = ('.png', '.jpg', '.jpeg', '.webp') if kind == 'image' else ('.mp4', '.mov')
            urls = [url for url in urls if url.split('?', 1)[0].lower().endswith(expected)]
            if not urls:
                raise ValueError('RunningHub 返回结果类型与任务不匹配')
            return {'assets': [common.download_result(job, url, Path(url.split('?', 1)[0]).suffix or ('.png' if kind == 'image' else '.mp4'), recoverable=True) for url in urls]}
    raise InterruptedError()


def _dimensions(job, params):
    raw = str(params.get('size') or job['input'].get('size') or '1024x1024').lower()
    try:
        width, height = (int(value) for value in raw.split('x', 1))
    except (TypeError, ValueError):
        width, height = 1024, 1024
    return max(240, min(width, 8192)), max(240, min(height, 8192))


def generate_image(worker, job, provider):
    model = str(model_for(provider, 'image')).strip()
    if model != DEFAULT_IMAGE_MODEL:
        raise ValueError('当前 RunningHub 图片适配器仅支持 Seedream 5 Pro 配置')
    refs = common.assets_for(job)
    if len(refs) > 10:
        raise ValueError('RunningHub Seedream 5 Pro 最多接受 10 张参考图')
    params = {**((provider.get('parameters') or {}).get('image') or {}), **(job['input'].get('parameters') or {})}
    width, height = _dimensions(job, params)
    root = _root(provider)
    with provider_egress.client(origin=provider['url'],timeout=120, headers=_headers(provider, False), trust_env=True) as client:
        remote = job.get('provider_job_id')
        if not remote:
            body = {
                'prompt': job['input']['prompt'], 'width': width, 'height': height,
                'resolution': str(params.get('resolution') or '2k'),
                'outputFormat': str(params.get('outputFormat') or 'jpeg'),
            }
            endpoint = '/openapi/v2/seedream-v5-pro/text-to-image'
            if refs:
                endpoint = '/openapi/v2/seedream-v5-pro/image-to-image'
                body['imageUrls'] = [_upload(client, root, asset) for asset in refs]
            value = common.checked(client.post(root + endpoint, json=body))
            remote = value.get('taskId')
            if not remote:
                raise ValueError(str(value.get('errorMessage') or 'RunningHub 图片任务未返回 taskId'))
            s.attach_provider_job_id(job['id'], str(remote))
        return _wait_task(worker, job, client, root, remote, 'image')


def generate_video(worker, job, provider):
    model = str(model_for(provider, 'video')).strip()
    if model not in (DEFAULT_VIDEO_MODEL, 'bytedance/seedance-2.5-global-token'):
        raise ValueError('当前 RunningHub 视频适配器仅支持 Seedance 2.5 Token 配置')
    refs = common.assets_for(job)
    tail = common.assets_by_ids(job, [job['input']['end_asset_id']])[0] if job['input'].get('end_asset_id') else None
    if tail and not refs:
        raise ValueError('RunningHub 尾帧模式必须同时指定首帧')
    if len(refs) > 30:
        raise ValueError('RunningHub Seedance 2.5 最多接受 30 张参考图')
    params = {**((provider.get('parameters') or {}).get('video') or {}), **(job['input'].get('parameters') or {})}
    duration = max(4, min(int(round(float(params.get('duration') or job['input'].get('duration') or 5))), 30))
    resolution = str(params.get('resolution') or '720p').replace(' ', '').lower()
    if resolution not in ('480p', '720p', '1080p', '2k', '4k'):
        resolution = '720p'
    base = {
        'prompt': job['input']['prompt'], 'duration': str(duration), 'resolution': resolution,
        'generateAudio': bool(params.get('generateAudio', params.get('generate_audio', True))),
        'watermark': bool(params.get('watermark', False)), 'returnLastFrame': False,
        'bitrateMode': str(params.get('bitrateMode') or 'standard'), 'seed': int(params.get('seed', -1)),
        'outputFormat': str(params.get('outputFormat') or 'mp4'),
    }
    root = _root(provider)
    global_segment = 'seedance-2.5-global-token' if 'global' in model else 'seedance-2.5-token'
    with provider_egress.client(origin=provider['url'],timeout=120, headers=_headers(provider, False), trust_env=True) as client:
        remote = job.get('provider_job_id')
        if not remote:
            dialogue_reference = bool(job['input'].get('dialogue_audio'))
            if dialogue_reference:
                from .volcengine_ark import _dialogue_reference_audio, _dialogue_reference_prompt
                worker.progress(job, '编排固定对白音频参考')
                endpoint = f'/openapi/v2/bytedance/{global_segment}/multimodal-video'
                body = {
                    **base,
                    'prompt': _dialogue_reference_prompt(job['input']['prompt'], len(refs)),
                    'audioUrls': [_dialogue_reference_audio(job, duration)],
                    'ratio': str(params.get('ratio') or job['input'].get('ratio') or 'adaptive'),
                    'realPersonMode': True, 'conversionSlots': ['all'], 'omniReferenceTaskType': 'auto',
                }
                if refs:
                    body['imageUrls'] = [_upload(client, root, asset) for asset in refs]
                if tail:
                    raise ValueError('RunningHub 固定对白多模态参考暂不与尾帧模式混用')
            elif not refs:
                endpoint = f'/openapi/v2/bytedance/{global_segment}/text-to-video'
                body = {**base, 'ratio': str(params.get('ratio') or job['input'].get('ratio') or '16:9'), 'webSearch': False}
            elif len(refs) == 1 or tail:
                endpoint = f'/openapi/v2/bytedance/{global_segment}/image-to-video'
                body = {**base, 'firstFrameUrl': _upload(client, root, refs[0]), 'ratio': 'adaptive', 'realPersonMode': True, 'conversionSlots': ['all']}
                if tail:
                    body['lastFrameUrl'] = _upload(client, root, tail)
            else:
                endpoint = f'/openapi/v2/bytedance/{global_segment}/multimodal-video'
                body = {**base, 'imageUrls': [_upload(client, root, asset) for asset in refs], 'ratio': str(params.get('ratio') or job['input'].get('ratio') or 'adaptive'), 'realPersonMode': True, 'conversionSlots': ['all'], 'omniReferenceTaskType': 'auto'}
            value = common.checked(client.post(root + endpoint, json=body))
            remote = value.get('taskId')
            if not remote:
                raise ValueError(str(value.get('errorMessage') or 'RunningHub 视频任务未返回 taskId'))
            s.attach_provider_job_id(job['id'], str(remote))
        return _wait_task(worker, job, client, root, remote, 'video')


def execute(worker, job, provider):
    if job['kind'] == 'image':
        return generate_image(worker, job, provider)
    if job['kind'] == 'video':
        return generate_video(worker, job, provider)
    raise ValueError('RunningHub 适配器不支持此任务类型')


def cancel(job, provider):
    # RunningHub Model API documents durable polling but currently exposes no
    # general cancellation endpoint for these model tasks.
    return False
