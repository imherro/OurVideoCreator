"""HC-ATOM (幻场 AI) unified text, image and asynchronous video adapter."""
from __future__ import annotations

import base64
import hashlib
import threading
import time
from urllib.parse import quote

import httpx

from .. import store as s
from .. import provider_egress
from . import common


DEFAULT_BASE_URL = 'https://api-aigc.fzyinghe.com'
LEGACY_BASE_URL = 'https://ai-aigc.fzyinghe.com'
KINDS = ('text', 'image', 'video')
SEEDANCE_PREFIXES = ('doubao-seedance-', 'dreamina-seedance-')
_asset_library_lock = threading.RLock()


def _root(provider):
    value = str(provider.get('url') or DEFAULT_BASE_URL).rstrip('/').removesuffix('/v1')
    # The administrator owns the exact frozen origin; no legacy host rewrites.
    return value


def text_base_url(provider):
    return _root(provider) + '/v1'


def _headers(provider, idempotency_key=None):
    key = str(provider.get('api_key') or '').strip()
    if not key:
        raise ValueError('幻场 AI 尚未配置 API Key')
    headers = {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}
    if idempotency_key:
        headers['Idempotency-Key'] = str(idempotency_key)
    return headers


def model_for(provider, kind):
    kind = 'text' if kind == 'storyboard' else kind
    return str((provider.get('models') or {}).get(kind) or provider.get('model') or '').strip()


def _unwrap(value):
    if isinstance(value, dict) and isinstance(value.get('data'), dict) and (
        'code' in value or 'msg' in value
    ):
        return value['data']
    return value


def _checked(response, recoverable=False):
    """Validate both HTTP status and HC's HTTP-200 business envelope."""
    value = common.checked(response, recoverable=recoverable)
    if isinstance(value, dict) and 'code' in value:
        code = value.get('code')
        if code not in (0, 200, '0', '200'):
            detail = value.get('msg') or value.get('message') or value.get('error') or code
            raise ValueError('幻场 AI 返回业务错误：' + str(detail)[:500])
    return value


def _catalog_kind(model_id, provider, item=None):
    configured = provider.get('models') if isinstance(provider.get('models'), dict) else {}
    for kind in KINDS:
        if model_id == str(configured.get(kind) or '').strip():
            return kind
    item = item or {}
    path = str(item.get('apiPath') or item.get('api_path') or '').lower()
    domain = str(item.get('domain') or item.get('type') or '').lower()
    lowered = model_id.lower()
    if 'video/generation' in path or 'video' in domain or any(
        token in lowered for token in (
            'video', 'seedance', 'kling', 'hailuo', 'veo', 'happyhorse', 'minimax-h3',
            '-t2v', '-i2v', '-r2v', 'videoedit',
        )
    ):
        return 'video'
    if 'image' in path or 'image' in domain or any(
        token in lowered for token in ('image', 'seedream', 'flux', 'midjourney', '-t2i', '-i2i', 'wan2.7')
    ):
        return 'image'
    if any(token in lowered for token in ('embedding', 'rerank', 'tts', 'speech', 'asr', 'music', 'superres')):
        return None
    return 'text'


def list_models(provider):
    """Read the authenticated catalogue. This endpoint does not run a model."""
    try:
        with provider_egress.client(origin=provider['url'],timeout=30, headers=_headers(provider), trust_env=True) as client:
            value = _checked(client.get(_root(provider) + '/v1/models'))
    except httpx.HTTPError as exc:
        raise ValueError('幻场 AI 连接失败，请检查网络、服务地址和代理设置') from exc
    data = value.get('data') if isinstance(value, dict) else None
    if isinstance(data, dict):
        data = data.get('models') or data.get('list')
    if not isinstance(data, list):
        raise ValueError('幻场 AI 模型目录返回格式不正确')
    result, seen = [], set()
    for item in data:
        if isinstance(item, str):
            item = {'id': item}
        if not isinstance(item, dict):
            continue
        model_id = str(item.get('id') or item.get('model') or item.get('innerCode') or '').strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        kind = _catalog_kind(model_id, provider, item)
        if not kind:
            continue
        result.append({
            'id': model_id,
            'name': str(item.get('name') or item.get('display_name') or model_id),
            'kind': kind,
            'capabilities': {
                'image_reference': kind in ('image', 'video'),
                'max_references': 10 if kind == 'image' else 1 if kind == 'video' else None,
                'end_frame': False,
            },
        })
    configured = provider.get('models') if isinstance(provider.get('models'), dict) else {}
    return sorted(result, key=lambda row: (row['id'] != configured.get(row['kind']), row['id']))


def check_configured_model(provider, kind):
    if kind not in KINDS:
        raise ValueError('幻场 AI 模型用途无效')
    model = model_for(provider, kind)
    if not model:
        raise ValueError(f'请先选择或填写幻场 AI {kind} 模型 ID')
    found = next((item for item in list_models(provider) if item['id'] == model), None)
    return {
        'status': 'listed' if found else 'unlisted',
        'kind': kind,
        'model': model,
        'message': '模型已在幻场 AI 目录中。' if found else '目录中未找到该 ID；可以保留手工填写值，实际生成时再验证。',
    }


def model_capabilities(provider, kind, model_id=None):
    target = str(model_id or model_for(provider, kind)).strip()
    model = next((item for item in list_models(provider) if item['id'] == target and item['kind'] == kind), None)
    if model:
        return model['capabilities']
    if kind == 'image' and target:
        return {'image_reference': True, 'max_references': 10, 'end_frame': False}
    return {'image_reference': kind == 'video', 'max_references': 1 if kind == 'video' else None, 'end_frame': False}


def _data_uri(asset):
    if asset.get('kind') != 'image':
        raise ValueError('幻场 AI 参考素材必须是图片')
    path = (s.ASSETS / str(asset.get('path') or '')).resolve()
    if not path.is_relative_to(s.ASSETS) or not path.is_file():
        raise ValueError('幻场 AI 参考图文件已丢失')
    mime = str(asset.get('mime') or 'image/png')
    if mime not in ('image/png', 'image/jpeg', 'image/webp'):
        raise ValueError('幻场 AI 参考图仅支持 PNG、JPEG 或 WebP')
    return f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode('ascii')


def _is_seedance(model):
    return str(model or '').strip().lower().startswith(SEEDANCE_PREFIXES)


def _seedance_duration(model, requested):
    value = int(round(float(requested or 5)))
    maximum = 30 if '2.5' in str(model) else 15
    if value > maximum:
        raise ValueError(f'幻场 {model} 视频时长不能超过 {maximum} 秒')
    return max(4, value)


def _seedance_prompt(prompt, requested, submitted):
    value = str(prompt)
    if requested == submitted:
        return value
    return value.replace(
        f'本镜头成片总时长必须为 {requested:g} 秒',
        f'本次模型生成长度为 {submitted:g} 秒；核心动作须在前 {requested:g} 秒内完成',
    )


def _post_task(worker, job, client, path, body):
    """Retry an idempotent create only when no HTTP response was received."""
    delays = (0, 2, 5)
    last = None
    for attempt, delay in enumerate(delays, start=1):
        if delay and worker.halt.wait(delay):
            raise InterruptedError()
        if worker.cancelled(job):
            raise InterruptedError()
        try:
            return _checked(client.post(path, json=body))
        except httpx.TransportError as exc:
            last = exc
            worker.progress(job, f'幻场 AI 提交连接中断，正在重试（{attempt}/3）')
    raise ValueError(f'幻场 AI 提交接口连接中断（{path}），已使用同一幂等编号重试 3 次') from last


def _task_value(client, path):
    return _unwrap(_checked(client.get(path), recoverable=True))


def _wait_task(worker, job, client, path, remote, kind):
    while not worker.halt.wait(3):
        if worker.cancelled(job):
            try:
                client.delete(path + '/' + quote(str(remote), safe=''))
            finally:
                raise InterruptedError()
        value = _task_value(client, path + '/' + quote(str(remote), safe=''))
        status = str(value.get('status') or '').upper()
        worker.progress(job, f'幻场 AI {"生成图片" if kind == "image" else "生成视频"}', value.get('progress'))
        if status in ('FAILED', 'ERROR', 'CANCELLED'):
            raise ValueError(str(value.get('failReason') or value.get('error') or '幻场 AI 生成失败'))
        if status in ('SUCCESS', 'SUCCEEDED', 'COMPLETED'):
            urls = value.get('resultUrls') if kind == 'image' else None
            if not isinstance(urls, list):
                urls = [value.get('resultUrl') or value.get('url') or value.get('video_url')]
            urls = [url for url in urls if isinstance(url, str) and url]
            if not urls:
                raise ValueError('幻场 AI 任务成功，但没有返回媒体地址')
            ext = '.png' if kind == 'image' else '.mp4'
            return {'assets': [common.download_result(job, url, ext, recoverable=True) for url in urls]}
    raise InterruptedError()


def _wait_seedance_v3(worker, job, client, path, remote):
    while not worker.halt.wait(3):
        if worker.cancelled(job):
            try:
                client.delete(path + '/' + quote(str(remote), safe=''))
            finally:
                raise InterruptedError()
        value = _checked(
            client.get(path + '/' + quote(str(remote), safe='')), recoverable=True,
        )
        status = str(value.get('status') or '').lower()
        worker.progress(job, {
            'queued': '幻场 Seedance 排队中',
            'pending': '幻场 Seedance 排队中',
            'running': '幻场 Seedance 生成中',
            'processing': '幻场 Seedance 生成中',
            'succeeded': '下载幻场 Seedance 视频',
            'success': '下载幻场 Seedance 视频',
        }.get(status, '查询幻场 Seedance 任务'))
        if status in ('failed', 'error', 'cancelled', 'canceled', 'expired'):
            detail = value.get('error') or value.get('message') or value.get('failReason')
            raise ValueError('幻场 Seedance 任务失败：' + str(detail or status)[:500])
        if status in ('succeeded', 'success', 'completed'):
            content = value.get('content') if isinstance(value.get('content'), dict) else {}
            target = content.get('video_url') or value.get('video_url') or value.get('resultUrl')
            if not target:
                raise ValueError('幻场 Seedance 任务成功，但没有返回 content.video_url')
            return {'assets': [common.download_result(job, target, '.mp4', recoverable=True)]}
    raise InterruptedError()


def _asset_account_hash(provider):
    """Scope cached remote ids to the API account without persisting its key."""
    key = str(provider.get('api_key') or '').strip()
    if not key:
        raise ValueError('幻场 AI 尚未配置 API Key')
    return hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]


def _configured_asset_group(provider):
    video = (provider.get('parameters') or {}).get('video') or {}
    return str(video.get('asset_group_id') or provider.get('asset_group_id') or '').strip()


def _asset_group(client, provider):
    configured = _configured_asset_group(provider)
    if configured:
        return configured
    provider_id = str(provider.get('id') or '').strip()
    account_hash = _asset_account_hash(provider)
    with _asset_library_lock:
        with s.db() as db:
            row = db.execute(
                'SELECT remote_group_id FROM provider_asset_groups WHERE provider_id=%s AND account_hash=%s',
                (provider_id, account_hash),
            ).fetchone()
        if row:
            return row['remote_group_id']
        value = _unwrap(_checked(client.post(
            _root(provider) + '/v3/asset-groups',
            json={
                'name': '安影 Seedance 虚拟人物素材',
                'description': '安影自动登记的虚拟人物首帧素材',
            },
        )))
        group_id = str(value.get('groupId') or value.get('group_id') or value.get('id') or '').strip()
        if not group_id:
            raise ValueError('幻场素材库创建素材组成功，但没有返回 groupId')
        now = time.time()
        with s.db() as db:
            db.execute('''INSERT INTO provider_asset_groups(provider_id,account_hash,remote_group_id,created,updated)
                VALUES(%s,%s,%s,%s,%s) ON CONFLICT(provider_id,account_hash) DO UPDATE SET
                remote_group_id=excluded.remote_group_id,updated=excluded.updated''',
                (provider_id, account_hash, group_id, now, now))
        return group_id


def _asset_mapping(provider, local_asset_id):
    with s.db() as db:
        return db.execute('''SELECT * FROM provider_asset_mappings
            WHERE provider_id=%s AND account_hash=%s AND local_asset_id=%s''', (
                str(provider.get('id') or '').strip(), _asset_account_hash(provider), local_asset_id,
            )).fetchone()


def _save_asset_mapping(provider, local_asset_id, remote_asset_id, group_id, status, error=None):
    now = time.time()
    with s.db() as db:
        db.execute('''INSERT INTO provider_asset_mappings(
                provider_id,account_hash,local_asset_id,remote_asset_id,remote_group_id,status,error,created,updated
            ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(provider_id,account_hash,local_asset_id) DO UPDATE SET
                remote_asset_id=excluded.remote_asset_id,remote_group_id=excluded.remote_group_id,
                status=excluded.status,error=excluded.error,updated=excluded.updated''', (
                str(provider.get('id') or '').strip(), _asset_account_hash(provider), local_asset_id,
                remote_asset_id, group_id, status, error, now, now,
            ))


def _register_seedance_asset(worker, job, client, provider, asset):
    """Create/reuse one HC virtual-person asset and wait for its durable review."""
    from ..provider_assets import public_asset_url

    local_id = str(asset.get('id') or '').strip()
    if not local_id:
        raise ValueError('幻场素材库无法识别本地首帧素材')
    mapping = _asset_mapping(provider, local_id)
    if mapping and str(mapping['status']).lower() == 'active':
        return 'asset://' + mapping['remote_asset_id']
    if mapping and str(mapping['status']).lower() == 'failed':
        raise ValueError('幻场虚拟人像素材审核失败：' + str(mapping['error'] or '素材未通过审核'))

    if mapping:
        group_id = mapping['remote_group_id']
        remote_id = mapping['remote_asset_id']
    else:
        with _asset_library_lock:
            # Recheck after acquiring the process-wide registration lock so two
            # concurrent cloud jobs never create duplicate remote assets.
            mapping = _asset_mapping(provider, local_id)
            if mapping:
                group_id = mapping['remote_group_id']
                remote_id = mapping['remote_asset_id']
            else:
                worker.progress(job, '正在创建或读取幻场虚拟人像素材组')
                group_id = _asset_group(client, provider)
                worker.progress(job, '正在把首帧登记到幻场虚拟人像素材库')
                value = _unwrap(_checked(client.post(
                    _root(provider) + '/v3/assets',
                    headers={'group_id': group_id},
                    json={
                        'url': public_asset_url(provider, local_id),
                        'name': str(asset.get('name') or '安影首帧'),
                        'assetType': 'Image',
                    },
                )))
                remote_id = str(value.get('id') or value.get('assetId') or '').strip()
                if not remote_id:
                    raise ValueError('幻场素材库登记首帧成功，但没有返回素材 ID')
                status = str(value.get('status') or 'Processing')
                _save_asset_mapping(provider, local_id, remote_id, group_id, status)

    while True:
        mapping = _asset_mapping(provider, local_id)
        status = str(mapping['status'] if mapping else 'Processing').lower()
        if status == 'active':
            return 'asset://' + remote_id
        if status == 'failed':
            raise ValueError('幻场虚拟人像素材审核失败：' + str(mapping['error'] or '素材未通过审核'))
        if worker.cancelled(job):
            raise InterruptedError()
        worker.progress(job, '等待幻场审核虚拟人像首帧')
        value = _unwrap(_checked(client.post(
            _root(provider) + '/v3/assets/detail',
            headers={'group_id': group_id},
            json={'assetId': remote_id},
        ), recoverable=True))
        remote_status = str(value.get('status') or 'Processing')
        error = value.get('failReason') or value.get('error') or value.get('message')
        if isinstance(error, dict):
            error = error.get('message') or str(error)
        _save_asset_mapping(provider, local_id, remote_id, group_id, remote_status, str(error) if error else None)
        if remote_status.lower() == 'active':
            return 'asset://' + remote_id
        if remote_status.lower() == 'failed':
            raise ValueError('幻场虚拟人像素材审核失败：' + str(error or '素材未通过审核'))
        if worker.halt.wait(3):
            raise InterruptedError()


def _generate_seedance_v3(worker, job, provider, model, refs, params):
    if len(refs) > 1:
        raise ValueError('幻场 Seedance 当前最多提交一张首帧，请移除多余引用')
    if job['input'].get('end_asset_id'):
        raise ValueError('幻场 Seedance 当前尚未开放尾帧绑定，请清除尾帧')
    path = _root(provider) + '/v3/video/tasks'
    remote = job.get('provider_job_id')
    with provider_egress.client(origin=provider['url'],timeout=120, headers=_headers(provider, job.get('submission_id')), trust_env=True) as client:
        if not remote:
            requested = float(params.get('duration') or job['input'].get('duration') or 5)
            submitted = _seedance_duration(model, requested)
            content = [{
                'type': 'text',
                'text': _seedance_prompt(job['input']['prompt'], requested, submitted),
            }]
            if refs:
                content.append({
                    'type': 'image_url',
                    'image_url': {'url': _register_seedance_asset(worker, job, client, provider, refs[0])},
                    'role': 'first_frame',
                })
            resolution = str(params.get('resolution') or '720p').lower()
            if resolution not in ('480p', '720p'):
                raise ValueError('幻场 Seedance 2.5 目前只支持 480p 或 720p，请修改项目视频分辨率')
            body = {
                'model': model,
                'content': content,
                'resolution': resolution,
                'ratio': 'adaptive' if refs else str(job['input'].get('ratio') or params.get('ratio') or '16:9'),
                'duration': submitted,
                'generate_audio': bool(params.get('generate_audio', True)),
            }
            value = _post_task(worker, job, client, path, body)
            remote = value.get('id') or value.get('taskId') or value.get('task_id')
            if not remote:
                raise ValueError('幻场 Seedance V3 未返回任务 id，请在幻场控制台核对')
            remote = str(remote)
            state = s.attach_provider_job_id(job['id'], remote)
            if state == 'cancelled':
                try:
                    cancelled = client.delete(path + '/' + quote(remote, safe='')).is_success
                except httpx.HTTPError:
                    cancelled = False
                s.cancelled_phase(job['id'], '已请求幻场取消远端任务' if cancelled else '本地已取消；幻场远端任务可能继续生成并产生费用')
                raise InterruptedError()
        return _wait_seedance_v3(worker, job, client, path, remote)


def generate_image(worker, job, provider):
    model = str(model_for(provider, 'image')).strip()
    if not model:
        raise ValueError('请填写幻场 AI 图片模型 ID')
    refs = common.assets_for(job)
    params = {**(provider.get('parameters') or {}).get('image', {}), **job['input'].get('parameters', {})}
    use_task = bool(refs) or params.get('mode') == 'task'
    with provider_egress.client(origin=provider['url'],timeout=120, headers=_headers(provider, job.get('submission_id')), trust_env=True) as client:
        if use_task:
            path = _root(provider) + str(params.get('task_path') or '/image/generation/tasks')
            remote = job.get('provider_job_id')
            if not remote:
                body = {
                    'model': model,
                    'input': {'prompt': job['input']['prompt']},
                    'parameters': {k: v for k, v in params.items() if k not in ('mode', 'task_path')},
                }
                if refs:
                    body['input']['images'] = [_data_uri(asset) for asset in refs]
                value = _unwrap(_checked(client.post(path, json=body)))
                remote = value.get('taskId') or value.get('task_id') or value.get('id')
                if not remote:
                    raise ValueError('幻场 AI 图片任务未返回 taskId')
                s.attach_provider_job_id(job['id'], str(remote))
            return _wait_task(worker, job, client, path, remote, 'image')
        body = {
            'model': model,
            'prompt': job['input']['prompt'],
            'n': int(params.get('n', 1)),
            'size': params.get('size') or job['input'].get('size') or '1024x1024',
            'response_format': params.get('response_format') or 'url',
        }
        worker.progress(job, '幻场 AI 生成图片')
        value = _checked(client.post(_root(provider) + '/v1/images/generations', json=body))
        outputs = []
        for item in value.get('data', []):
            if item.get('url'):
                outputs.append(common.download_result(job, item['url'], '.png'))
            elif item.get('b64_json'):
                path = s.DATA / (s.uid('hc-image-') + '.png')
                try:
                    path.write_bytes(base64.b64decode(item['b64_json']))
                    outputs.append(common.register(job, path, '幻场 AI 生成图.png'))
                finally:
                    path.unlink(missing_ok=True)
        if not outputs:
            raise ValueError('幻场 AI 未返回可下载的图片')
        return {'assets': outputs}


def generate_video(worker, job, provider):
    model = str(model_for(provider, 'video')).strip()
    if not model:
        raise ValueError('请填写幻场 AI 视频模型 ID')
    refs = common.assets_for(job)
    params = {**(provider.get('parameters') or {}).get('video', {}), **job['input'].get('parameters', {})}
    if _is_seedance(model):
        return _generate_seedance_v3(worker, job, provider, model, refs, params)
    if job['input'].get('end_asset_id'):
        raise ValueError('幻场 AI 通用视频接口暂未声明尾帧协议，请清除尾帧')
    if len(refs) > 1:
        raise ValueError('幻场 AI 通用视频接口最多提交一张参考图')
    path = _root(provider) + str(params.pop('task_path', None) or '/video/generation/tasks')
    with provider_egress.client(origin=provider['url'],timeout=120, headers=_headers(provider, job.get('submission_id')), trust_env=True) as client:
        remote = job.get('provider_job_id')
        if not remote:
            body = {**params, 'model': model, 'prompt': job['input']['prompt']}
            if refs:
                body['image'] = _data_uri(refs[0])
            value = _unwrap(_post_task(worker, job, client, path, body))
            remote = value.get('taskId') or value.get('task_id') or value.get('id')
            if not remote:
                raise ValueError('幻场 AI 视频任务未返回 taskId')
            s.attach_provider_job_id(job['id'], str(remote))
        return _wait_task(worker, job, client, path, remote, 'video')


def execute(worker, job, provider):
    if job['kind'] == 'image':
        return generate_image(worker, job, provider)
    if job['kind'] == 'video':
        return generate_video(worker, job, provider)
    raise ValueError('幻场 AI 适配器不支持此任务类型')


def cancel(job, provider):
    remote = job.get('provider_job_id')
    if not remote:
        return False
    kind = job.get('kind')
    section = ((provider.get('parameters') or {}).get(kind) or {})
    model = str(model_for(provider, 'video')).strip()
    default = ('/image/generation/tasks' if kind == 'image' else
               '/v3/video/tasks' if _is_seedance(model) else '/video/generation/tasks')
    path = _root(provider) + str(section.get('task_path') or default) + '/' + quote(str(remote), safe='')
    try:
        with provider_egress.client(origin=provider['url'],timeout=20, headers=_headers(provider), trust_env=True) as client:
            return client.delete(path).is_success
    except httpx.HTTPError:
        return False
