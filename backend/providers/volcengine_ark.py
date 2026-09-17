"""Volcengine Ark adapters for Seedream images and Seedance video tasks."""
import base64
import subprocess
from urllib.parse import quote

import httpx
from PIL import Image

from .. import store as s
from .. import provider_egress
from ..media import ffmpeg_executable, probe
from . import common


DEFAULT_BASE_URL = 'https://ark.cn-beijing.volces.com/api/v3'
DEFAULT_VIDEO_MODEL = 'doubao-seedance-2-5-260628'
SEEDANCE_25_PREFIX = 'doubao-seedance-2-5'


def seedance_submission_duration(model, requested):
    """Return the provider duration without changing canonical shot timing."""
    duration = int(requested)
    if str(model).lower().startswith(SEEDANCE_25_PREFIX):
        return max(4, duration)
    return duration


def seedance_submission_prompt(prompt, requested, submitted):
    value = str(prompt)
    if submitted == requested:
        return value
    return value.replace(
        f'本镜头成片总时长必须为 {requested:g} 秒',
        f'本次模型生成长度为 {submitted:g} 秒；核心动作须在前 {requested:g} 秒内完成',
    )


DISABLED_VIDEO_PREFIXES = ('doubao-seedance-2-0',)
SUPPORTED_REFERENCE_FORMATS = {'JPEG': 'image/jpeg', 'PNG': 'image/png'}
MAX_REFERENCE_BYTES = 10 * 1024 * 1024
MAX_REFERENCE_DIMENSION = 6000
MAX_AUDIO_REFERENCE_BYTES = 15 * 1024 * 1024
DIALOGUE_REFERENCE_MODE = 'seedance_reference'


def model_for(provider, kind):
    kind = 'text' if kind == 'storyboard' else kind
    return str(provider.get('models', {}).get(kind) or provider.get('model') or '').strip()


def _headers(provider):
    key = str(provider.get('api_key') or '').strip()
    if not key:
        raise ValueError('火山方舟尚未配置 ARK API Key')
    return {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}


def _root(provider):
    return str(provider.get('url') or DEFAULT_BASE_URL).rstrip('/')


def max_image_references(provider):
    parameters = provider.get('parameters') if isinstance(provider.get('parameters'), dict) else {}
    image = parameters.get('image') if isinstance(parameters.get('image'), dict) else {}
    value = image.get('max_references', 10)
    try:
        return max(1, min(int(value), 10))
    except (TypeError, ValueError):
        raise ValueError('火山方舟参考图上限必须是 1–10 的整数')


def _catalog_kind(model_id, provider, item=None):
    """Infer the studio lane for one Ark catalog item.

    Ark endpoint IDs do not encode a capability.  A model already assigned in
    this provider therefore wins over the public-model naming convention.
    """
    model_id = str(model_id or '').strip()
    configured = provider.get('models') if isinstance(provider.get('models'), dict) else {}
    for kind in ('text', 'image', 'video'):
        if model_id and model_id == str(configured.get(kind) or '').strip():
            return kind
    domain = str((item or {}).get('domain') or '').lower()
    outputs = (item or {}).get('modalities', {}).get('output_modalities', [])
    if domain == 'imagegeneration' or 'image' in outputs:
        return 'image'
    if domain == 'videogeneration' or 'video' in outputs:
        return 'video'
    lowered = model_id.lower()
    if 'seedream' in lowered or 'image' in lowered:
        return 'image'
    if 'seedance' in lowered or 'video' in lowered:
        return 'video'
    # Do not offer specialist endpoints in the chat-model picker merely because
    # they are neither Seedream nor Seedance.
    if any(token in lowered for token in ('embedding', 'rerank', 'speech', 'tts', 'asr')):
        return None
    return 'text'


def list_models(provider):
    """Return the authenticated Ark model catalog without running a model."""
    try:
        with provider_egress.client(origin=provider['url'],timeout=30, headers=_headers(provider), trust_env=True) as client:
            value = common.checked(client.get(_root(provider) + '/models'))
    except httpx.HTTPError as exc:
        raise ValueError('火山方舟连接失败，请检查网络、服务地址和代理设置') from exc
    data = value.get('data')
    if not isinstance(data, list):
        raise ValueError('火山方舟模型目录返回格式不正确')
    models = []
    seen = set()
    configured = provider.get('models') if isinstance(provider.get('models'), dict) else {}
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get('id') or '').strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        kind = _catalog_kind(model_id, provider, item)
        if not kind:
            continue
        if kind == 'video' and model_id.lower().startswith(DISABLED_VIDEO_PREFIXES):
            continue
        lifecycle = str(item.get('status') or 'Active')
        if lifecycle.lower() == 'shutdown':
            continue
        modalities = item.get('modalities') if isinstance(item.get('modalities'), dict) else {}
        inputs = modalities.get('input_modalities', [])
        configured_for_kind = model_id == str(configured.get(kind) or '').strip()
        capabilities = {
            'image_reference': (
                kind == 'image' and 'image' in inputs
                or kind == 'video' and any(mode in inputs for mode in ('image', 'first_frame', 'first_last_frame'))
                or not inputs and configured_for_kind and kind in ('image', 'video')
            ),
            'max_references': max_image_references(provider) if kind == 'image' else 1 if kind == 'video' else None,
            'end_frame': kind == 'video' and (
                'first_last_frame' in inputs or 'seedance-2-' in model_id.lower() or not inputs and configured_for_kind
            ),
        }
        models.append({
            'id': model_id,
            'name': model_id + (' · 即将下线' if lifecycle.lower() == 'retiring' else ''),
            'kind': kind,
            'lifecycle': lifecycle,
            'capabilities': capabilities,
        })
    return sorted(models, key=lambda model: (model['id'] != configured.get(model['kind']), model['id']), reverse=False)


def model_capabilities(provider, kind, model_id=None):
    """Resolve capabilities for the concrete Ark model selected by a job."""
    target = str(model_id or model_for(provider, kind) or '').strip()
    if not target:
        raise ValueError('请先选择火山方舟模型')
    model = next(
        (item for item in list_models(provider) if item.get('id') == target and item.get('kind') == kind),
        None,
    )
    if not model:
        label = {'text': '文本', 'image': '图片', 'video': '视频'}.get(kind, kind)
        raise ValueError(f'火山方舟{label}模型目录中找不到所选模型，无法核对生成能力')
    return model.get('capabilities') or {}


def check_configured_model(provider, kind):
    """Check catalog visibility for a configured model without billed generation."""
    if kind not in ('text', 'image', 'video'):
        raise ValueError('火山方舟模型用途无效')
    model = model_for(provider, kind)
    if not model:
        label = {'text': '文本', 'image': '图片', 'video': '视频'}[kind]
        raise ValueError(f'请先选择或填写火山方舟{label}模型 ID')
    catalog = list_models(provider)
    found = next((item for item in catalog if item['id'] == model), None)
    if found:
        return {'status': 'listed', 'kind': kind, 'model': model, 'message': '模型已在方舟目录中；实际调用权限以首次生成结果为准'}
    return {
        'status': 'unlisted',
        'kind': kind,
        'model': model,
        'message': '方舟模型目录中未找到该 ID；可保留自定义接入点，实际生成时再验证',
    }


def load_image_asset(asset):
    """Load and decode an internal image without applying model-specific limits."""
    if asset.get('kind') != 'image':
        raise ValueError('火山方舟参考素材必须是图片')
    path = (s.ASSETS / str(asset.get('path') or '')).resolve()
    if not path.is_relative_to(s.ASSETS) or not path.is_file():
        raise ValueError('火山方舟参考图文件已丢失')
    try:
        with Image.open(path) as image:
            mime = SUPPORTED_REFERENCE_FORMATS.get(image.format or '')
            width, height = image.size
            image.verify()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValueError('火山方舟无法读取参考图，请重新上传 PNG 或 JPEG') from exc
    if not mime:
        raise ValueError('火山方舟参考图仅支持 PNG 或 JPEG')
    return {'path':path,'size':path.stat().st_size,'mime':mime,'width':width,'height':height}


def resolve_image_reference(asset):
    """Resolve an internal asset to the data URI accepted by Seedream."""
    loaded=load_image_asset(asset)
    if loaded['size'] > MAX_REFERENCE_BYTES:
        raise ValueError('火山方舟单张参考图不能超过 10MB')
    width,height=loaded['width'],loaded['height']
    if width <= 14 or height <= 14 or not 1 / 3 <= width / height <= 3:
        raise ValueError('火山方舟参考图尺寸或宽高比不符合要求（边长需大于 14，宽高比 1:3–3:1）')
    if width > MAX_REFERENCE_DIMENSION or height > MAX_REFERENCE_DIMENSION:
        raise ValueError('火山方舟参考图长边不能超过 6000 像素')
    return f'data:{loaded["mime"]};base64,' + base64.b64encode(loaded['path'].read_bytes()).decode('ascii')


def seedance_frame(asset):
    """Validate and resolve one local still for a Seedance frame role."""
    loaded=load_image_asset(asset)
    if loaded['size'] > MAX_REFERENCE_BYTES:
        raise ValueError('火山方舟视频首帧不能超过 10MB')
    width,height=loaded['width'],loaded['height']
    if width <= 14 or height <= 14 or not 1 / 3 <= width / height <= 3:
        raise ValueError('火山方舟视频首帧尺寸或宽高比不符合要求（边长需大于 14，宽高比 1:3–3:1）')
    if width > MAX_REFERENCE_DIMENSION or height > MAX_REFERENCE_DIMENSION:
        raise ValueError('火山方舟视频首帧长边不能超过 6000 像素')
    return {
        'url':f'data:{loaded["mime"]};base64,' + base64.b64encode(loaded['path'].read_bytes()).decode('ascii'),
        'width':width,
        'height':height,
    }


def resolve_seedance_frame(asset):
    return seedance_frame(asset)['url']


def _image_result(worker, job, value):
    outputs = []
    for item in value.get('data', []):
        if worker.cancelled(job):
            raise InterruptedError()
        if item.get('url'):
            outputs.append(common.download_result(job, item['url'], '.png'))
        elif item.get('b64_json'):
            path = s.DATA / (s.uid('ark-image-') + '.png')
            try:
                path.write_bytes(base64.b64decode(item['b64_json']))
                outputs.append(common.register(job, path, 'Seedream 生成图.png'))
            finally:
                path.unlink(missing_ok=True)
    if not outputs:
        raise ValueError('火山方舟未返回可下载的图像')
    return {'assets': outputs}


def generate_image(worker, job, provider):
    assets = common.assets_for(job)
    limit = max_image_references(provider)
    if len(assets) > limit:
        raise ValueError(f'当前火山方舟图片模型最多支持 {limit} 张参考图，请移除多余引用')
    model = model_for(provider, 'image')
    if not model:
        raise ValueError('请填写火山方舟图片模型 ID')
    params = {**provider.get('parameters', {}).get('image', {}), **job['input'].get('parameters', {})}
    body = {
        'model': model,
        'prompt': job['input']['prompt'],
        'size': job['input'].get('size') or params.get('size') or '2K',
        'response_format': 'url',
        'watermark': bool(params.get('watermark', False)),
    }
    if assets:
        references = [resolve_image_reference(asset) for asset in assets]
        body['image'] = references[0] if len(references) == 1 else references
    worker.progress(job, '火山方舟生成图像')
    with provider_egress.client(origin=provider['url'],timeout=600, headers=_headers(provider), trust_env=True) as client:
        return _image_result(worker, job, common.checked(client.post(_root(provider) + '/images/generations', json=body)))


def _video_url(value):
    content = value.get('content') or value.get('result') or {}
    if isinstance(content, dict):
        return content.get('video_url') or content.get('url')
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and (item.get('video_url') or item.get('url')):
                return item.get('video_url') or item.get('url')
    return value.get('video_url') or value.get('output_url')


def _mux_fixed_dialogue(worker, job, video_path):
    tracks = job['input'].get('dialogue_audio') or []
    assets = common.assets_by_ids(job, [item['assetId'] for item in tracks])
    if len(assets) != len(tracks) or any(item.get('kind') != 'audio' for item in assets):
        raise ValueError('固定对白音频已失效，请重新生成对白后再生成视频')
    output = s.DATA / (s.uid('dialogue-video-') + '.mp4')
    args = [ffmpeg_executable(), '-y', '-i', str(video_path)]
    for asset in assets:
        args += ['-i', str(s.ASSETS / asset['path'])]
    filters = []
    labels = []
    for index, track in enumerate(tracks, 1):
        delay = max(0, round(float(track.get('start') or 0) * 1000))
        label = f'd{index}'
        filters.append(
            f'[{index}:a]aresample=48000,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,'
            f'adelay={delay}|{delay}[{label}]'
        )
        labels.append(f'[{label}]')
    source_duration = float(probe(video_path).get('duration') or 0)
    if source_duration <= 0:
        raise ValueError('Seedance 返回的视频时长无效，无法写入固定对白')
    requested_duration = float(job['input'].get('shot_duration') or 0)
    duration = min(source_duration, requested_duration) if requested_duration > 0 else source_duration
    filters.append(
        ''.join(labels) + f'amix=inputs={len(labels)}:duration=longest:normalize=0,'
        f'alimiter=limit=.95,apad,atrim=duration={duration:.6f}[dialogue]'
    )
    worker.progress(job, '写入角色固定音色')
    command = args + [
        '-filter_complex', ';'.join(filters), '-map', '0:v:0', '-map', '[dialogue]',
        '-c:v', 'copy', '-c:a', 'aac', '-ac', '2', '-ar', '48000',
        '-t', f'{duration:.6f}', str(output),
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=300,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        if completed.returncode != 0:
            detail = completed.stderr.decode('utf-8', errors='replace')[-1200:]
            raise ValueError('固定对白写入视频失败：' + detail)
        return common.register(job, output, '生成结果 · 固定角色音色.mp4')
    finally:
        output.unlink(missing_ok=True)


def _dialogue_reference_audio(job, duration, *, public_provider=None):
    """Compile locked dialogue takes into one timing-aware Seedance reference."""
    tracks = job['input'].get('dialogue_audio') or []
    if not tracks:
        raise ValueError('固定对白音频为空，请重新生成对白后再生成视频')
    assets = common.assets_by_ids(job, [item['assetId'] for item in tracks])
    if len(assets) != len(tracks) or any(item.get('kind') != 'audio' for item in assets):
        raise ValueError('固定对白音频已失效，请重新生成对白后再生成视频')
    output = s.DATA / (s.uid('seedance-dialogue-reference-') + '.mp3')
    args = [ffmpeg_executable(), '-y']
    for asset in assets:
        path = (s.ASSETS / str(asset.get('path') or '')).resolve()
        if not path.is_relative_to(s.ASSETS) or not path.is_file():
            raise ValueError('固定对白音频文件已丢失，请重新生成对白')
        args += ['-i', str(path)]
    filters = []
    labels = []
    for index, track in enumerate(tracks):
        delay = max(0, round(float(track.get('start') or 0) * 1000))
        label = f'ref{index}'
        filters.append(
            f'[{index}:a]aresample=24000,aformat=sample_fmts=fltp:sample_rates=24000:channel_layouts=mono,'
            f'adelay={delay}[{label}]'
        )
        labels.append(f'[{label}]')
    filters.append(
        ''.join(labels) + f'amix=inputs={len(labels)}:duration=longest:normalize=0,'
        f'alimiter=limit=.95,apad,atrim=duration={float(duration):.6f}[reference]'
    )
    command = args + [
        '-filter_complex', ';'.join(filters), '-map', '[reference]',
        '-c:a', 'libmp3lame', '-b:a', '128k', '-ar', '24000', '-ac', '1', str(output),
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=180,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        if completed.returncode != 0:
            detail = completed.stderr.decode('utf-8', errors='replace')[-1200:]
            raise ValueError('固定对白音频参考编排失败：' + detail)
        if not output.is_file() or output.stat().st_size <= 0:
            raise ValueError('固定对白音频参考编排失败：未生成音频文件')
        if output.stat().st_size > MAX_AUDIO_REFERENCE_BYTES:
            raise ValueError('固定对白音频参考超过 15MB，请缩短镜头对白后重试')
        if public_provider is not None:
            from ..provider_assets import public_asset_url
            asset = common.register(job, output, name='固定对白时序参考.mp3', category='voice', asset_source='derived')
            return public_asset_url(public_provider, asset['id'])
        return 'data:audio/mpeg;base64,' + base64.b64encode(output.read_bytes()).decode('ascii')
    finally:
        output.unlink(missing_ok=True)


def _dialogue_reference_prompt(prompt, image_count=0):
    visual = ''
    if image_count:
        visual = '使用@图片1作为镜头起始构图、角色外观和场景视觉参考；'
        if image_count > 1:
            visual += '使用@图片2作为镜头结束构图参考；'
    return (
        str(prompt).rstrip()
        + '\n\n[Seedance 全模态参考]\n'
        + visual
        + '严格使用@音频1作为本镜头对白的音色、情绪、语速、节奏和开口时序参考；'
        + '角色按对白内容表演并准确匹配口型，不得改词，不得增加额外对白。'
    )


def generate_video(worker, job, provider):
    multimodal = (job['input'].get('generation_mode') or {}).get('requested') == 'multimodal'
    if len(job['input'].get('asset_ids',[]))>(provider.get('capabilities',{}).get('max_references',1) if multimodal else 1):
        raise ValueError('当前火山方舟视频最多接受一张首帧，请移除多余引用')
    if job['input'].get('end_asset_id') and len(job['input'].get('asset_ids',[]))!=1:
        raise ValueError('使用火山方舟尾帧时必须同时指定一张首帧')
    model = model_for(provider, 'video')
    if not model:
        raise ValueError('请填写火山方舟视频模型 ID')
    selected_model = str(model).strip()
    if selected_model.lower().startswith(DISABLED_VIDEO_PREFIXES) and not multimodal:
        raise ValueError('安影已停用 Seedance 2.0，请在项目设置中选择 Doubao-Seedance-2.5')
    root = _root(provider)
    remote = job.get('provider_job_id')
    params = {**provider.get('parameters', {}).get('video', {}), **job['input'].get('parameters', {})}
    dialogue_reference = (
        bool(job['input'].get('dialogue_audio'))
        and job['input'].get('dialogue_audio_mode') == DIALOGUE_REFERENCE_MODE
    )
    if dialogue_reference and not selected_model.lower().startswith(SEEDANCE_25_PREFIX) and not multimodal:
        raise ValueError('固定对白音频参考需要 Doubao-Seedance-2.5，请在项目设置中选择该模型')
    with provider_egress.client(origin=provider['url'],timeout=120, headers=_headers(provider), trust_env=True) as client:
        if not remote:
            assets=common.assets_for(job)
            content=[{'type': 'text', 'text': job['input']['prompt']}]
            if multimodal:
                for asset in assets:
                    content.append({'type':'image_url', 'image_url':{'url':seedance_frame(asset)['url']}, 'role':'reference_image'})
                if job['input'].get('motion_reference'):
                    from ..motion_references import silent_motion_asset
                    from ..provider_assets import public_asset_url
                    content.append({'type':'video_url', 'role':'reference_video',
                                    'video_url':{'url':public_asset_url(provider,silent_motion_asset(job)['id'])}})
            elif assets:
                first=seedance_frame(assets[0])
                content.append({
                    'type':'image_url',
                    'image_url':{'url':first['url']},
                    # Ark rejects first/last-frame roles mixed with reference
                    # audio. In full-modal mode the same still is a visual
                    # reference and the prompt asks for it as the opening shot.
                    'role':'reference_image' if dialogue_reference else 'first_frame',
                })
                if job['input'].get('end_asset_id'):
                    tail=common.assets_for({**job,'input':{'asset_ids':[job['input']['end_asset_id']]}})[0]
                    last=seedance_frame(tail)
                    if first['width']*last['height']!=last['width']*first['height']:
                        raise ValueError('火山方舟首帧与尾帧的宽高比必须一致')
                    content.append({
                        'type':'image_url',
                        'image_url':{'url':last['url']},
                        'role':'reference_image' if dialogue_reference else 'last_frame',
                    })
            requested_duration = int(params.get('duration', 5))
            # Project shots may be shorter than Ark's generation window. Keep
            # their canonical duration unchanged and generate the minimum valid
            # Seedance 2.5 clip; timeline assembly trims it back to the plan.
            submission_duration = seedance_submission_duration(selected_model, requested_duration)
            prompt = seedance_submission_prompt(
                job['input']['prompt'], requested_duration, submission_duration,
            )
            if dialogue_reference:
                worker.progress(job, '编排固定对白音频参考')
                if not multimodal:
                    prompt = _dialogue_reference_prompt(
                        prompt, sum(item.get('role') == 'reference_image' for item in content),
                    )
                content.append({
                    'type': 'audio_url',
                    'audio_url': {'url': _dialogue_reference_audio(job, submission_duration)},
                    'role': 'reference_audio',
                })
            body = {
                'model': selected_model,
                'content': [{**item, 'text': prompt} if item.get('type') == 'text' else item for item in content],
                'duration': submission_duration,
                'resolution': str(params.get('resolution', '720p')),
                'generate_audio': True if dialogue_reference else (
                    False if job['input'].get('dialogue_audio') else bool(params.get('generate_audio', True))
                ),
            }
            if job['input'].get('voice_samples'):
                from ..voice_samples import submission_assets, sample_data_uri
                body['content'].extend({'type':'audio_url','audio_url':{'url':sample_data_uri(asset)},'role':'reference_audio'}
                                       for asset in submission_assets(job))
                body['generate_audio']=True
            if (dialogue_reference or multimodal) and selected_model.lower().startswith(SEEDANCE_25_PREFIX):
                body['omni_reference_task_type'] = 'reference'
            # Seedance derives image-to-video output ratio from the first frame
            # and rejects an explicit ratio for first-frame/first-last-frame jobs.
            if not assets or dialogue_reference or multimodal:
                body['ratio'] = str(job['input'].get('ratio') or params.get('ratio') or '16:9')
            if worker.cancelled(job):
                raise InterruptedError()
            value = common.checked(client.post(root + '/contents/generations/tasks', json=body))
            remote = value.get('id') or value.get('task_id')
            if not remote:
                raise ValueError('火山方舟未返回 task id，请在控制台核对任务后再提交')
            remote = str(remote)
            # Persist before the first poll so a process restart resumes this task.
            state=s.attach_provider_job_id(job['id'],remote)
            if state=='cancelled':
                try:
                    response=client.delete(root + '/contents/generations/tasks/' + quote(remote, safe=''))
                    phase=('已取消本地等待，并已请求供应商取消远端任务' if response.is_success
                           else '本地已取消；供应商可能继续生成并产生费用')
                except httpx.HTTPError:
                    phase='本地已取消；供应商可能继续生成并产生费用'
                s.cancelled_phase(job['id'],phase)
                raise InterruptedError()
        interval = max(1, min(int(params.get('poll_interval', 5)), 60))
        while not worker.halt.wait(interval):
            if worker.cancelled(job):
                raise InterruptedError()
            value = common.checked(client.get(root + '/contents/generations/tasks/' + quote(remote, safe='')),recoverable=True)
            status = str(value.get('status') or '').lower()
            if status not in ('queued', 'pending', 'running', 'processing', 'succeeded', 'success', 'failed', 'cancelled', 'canceled', 'expired'):
                raise ValueError('火山方舟返回未知任务状态，请保留任务编号核对：' + str(value.get('status')))
            worker.progress(job, {
                'queued': '火山方舟排队中', 'pending': '火山方舟排队中',
                'running': '火山方舟生成中', 'processing': '火山方舟生成中',
                'succeeded': '下载 Seedance 视频', 'success': '下载 Seedance 视频',
            }.get(status, '查询火山方舟任务'))
            if status in ('failed', 'cancelled', 'canceled'):
                detail = value.get('error') or value.get('message') or '请在火山方舟控制台核对任务详情'
                raise ValueError('火山方舟视频任务' + ('生成失败' if status == 'failed' else '已取消') + '：' + str(detail)[:500])
            if status=='expired':
                raise ValueError('火山方舟任务已过期，原任务无法继续查询，请重新生成')
            if status in ('succeeded', 'success'):
                target = _video_url(value)
                if not target:
                    raise ValueError('火山方舟任务成功但未返回视频下载地址')
                # Jobs created before audio-reference support did not carry a
                # mode marker and still need the legacy exact-audio mux path.
                if job['input'].get('dialogue_audio') and not dialogue_reference:
                    video_path = common.download_file(target, '.mp4', recoverable=True)
                    try:
                        return {'assets': [_mux_fixed_dialogue(worker, job, video_path)]}
                    finally:
                        video_path.unlink(missing_ok=True)
                return {'assets': [common.download_result(job, target, '.mp4', recoverable=True)]}
    raise InterruptedError()


def execute(worker, job, provider):
    if job['kind'] == 'image':
        return generate_image(worker, job, provider)
    if job['kind'] == 'video':
        return generate_video(worker, job, provider)
    raise ValueError('火山方舟媒体适配器仅处理图像和视频任务')


def cancel(job, provider):
    remote = job.get('provider_job_id')
    if not remote:
        return None
    try:
        with provider_egress.client(origin=provider['url'],timeout=20, headers=_headers(provider), trust_env=True) as client:
            response=client.delete(_root(provider) + '/contents/generations/tasks/' + quote(str(remote), safe=''))
            return response.is_success
    except (httpx.HTTPError, ValueError):
        # The local cancelled state still prevents polling and asset registration.
        return False
