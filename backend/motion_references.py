"""Canonical shot references, local read-only preview, first-submit media preparation."""
from __future__ import annotations

import copy
import hashlib
import math
import re
import subprocess
import threading
from pathlib import Path

from . import store as s
from .media import ffmpeg_executable, probe
from .providers import common
from .reference_compiler import _binding_rows, _primary_reference, _version_chain
from .video_dialogue import _shot_for_video_node

VERSION = 'shot-motion-v1'
START, END = '[镜头动作参考]', '[/镜头动作参考]'
MODES = {'legacy', 'multimodal', 'first_frame', 'first_last_frame'}
_DECODED = set()
_DECODE_LOCK = threading.Lock()
_DERIVATIVE_LOCK = threading.Lock()


def protocol_limits(kind, model):
    """Private model identity is checked when publishing; only limits are public."""
    model = str(model or '').lower()
    supported = ((kind == 'volcengine_ark' and re.match(r'^doubao-seedance-2-(0|5)(-|$)', model))
                 or (kind == 'hc_atom' and re.match(r'^(doubao|dreamina)-seedance-2\.(0|5)(-|$)', model))
                 or (kind == 'runninghub' and model in (
                     'bytedance/seedance-2.5-token', 'bytedance/seedance-2.5-global-token')))
    if not supported:
        raise ValueError('当前适配器/模型尚未接通多模态参考协议；不会更换模型或删除绑定')
    newer = '2.5' in model or '2-5' in model
    return {'max_images': 30 if newer else 9, 'max_duration': 30 if newer else 15,
            'max_reference_duration': 30 if newer else 15, 'audio_only': newer}


def capability(provider):
    caps = (provider or {}).get('capabilities') or {}
    if caps.get('multimodal_reference') is not True:
        raise ValueError('所选平台模型未发布多模态参考能力，绑定会保留')
    return {'max_images': caps.get('max_references', 1),
            'max_duration': caps['max_video_duration'],
            'max_reference_duration': caps['max_reference_duration'],
            'audio_only': caps.get('audio_only_reference') is True,
            'video': caps.get('video_reference') is True}


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inspect_motion(asset, caps):
    path = (s.ASSETS / asset['path']).resolve()
    if not path.is_relative_to(s.ASSETS.resolve()) or not path.is_file():
        raise ValueError('动作参考视频文件不存在')
    if asset.get('kind') != 'video' or path.suffix.lower() != '.mp4':
        raise ValueError('动作参考仅接受 MP4 视频，请先在外部导出为 MP4')
    if path.stat().st_size > 200 * 1024**2:
        raise ValueError('动作参考视频不能超过 200 MB')
    with path.open('rb') as stream:
        if b'ftyp' not in stream.read(64):
            raise ValueError('动作参考不是真实 MP4 文件')
    metadata = probe(path)
    w, h, fps, duration = (metadata.get(key) or 0 for key in ('width', 'height', 'fps', 'duration'))
    if not all(math.isfinite(float(v)) for v in (w, h, fps, duration)) or not w or not h:
        raise ValueError('动作参考缺少可读取的视频流')
    if not 2 <= duration <= caps['max_reference_duration']:
        raise ValueError(f"动作参考时长需为 2–{caps['max_reference_duration']} 秒，请在外部裁剪")
    if not (300 <= w <= 6000 and 300 <= h <= 6000 and .4 <= w / h <= 2.5 and 407696 <= w * h <= 8295044):
        raise ValueError('动作参考尺寸不符合要求：边长 300–6000，宽高比 0.4–2.5，总像素 407696–8295044')
    if metadata.get('video_codec') not in ('h264', 'hevc'):
        raise ValueError('动作参考 MP4 需使用 H.264 或 H.265 编码')
    if not 24 <= fps <= 60:
        raise ValueError('动作参考帧率需为 24–60 FPS')
    digest = file_hash(path)
    with _DECODE_LOCK:
        if digest not in _DECODED:
            checked = subprocess.run([ffmpeg_executable(), '-v', 'error', '-xerror', '-i', str(path),
                '-map', '0:v:0', '-an', '-f', 'null', '-'], capture_output=True, timeout=120,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if checked.returncode:
                raise ValueError('动作参考视频无法完整解码，请重新导出 MP4')
            # Bounded in-process cache; preview never writes a DB row or disk marker.
            if len(_DECODED) >= 256:
                _DECODED.clear()
            _DECODED.add(digest)
    return {**metadata, 'bytes': path.stat().st_size, 'sha256': digest}


def resolve_generation_mode(document, shot):
    requested = (shot or {}).get('videoReferenceMode') or document.get('videoReferenceMode') or 'legacy'
    if requested not in MODES:
        raise ValueError('视频生成模式无效')
    return {'requested': requested, 'actual': requested,
            'source': 'shot' if (shot or {}).get('videoReferenceMode') else 'project'}


def validate_shot_reference(shot):
    if shot.get('videoReferenceMode') not in (None, '', *MODES):
        raise ValueError('视频生成模式无效')
    reference = shot.get('motionReference')
    if reference is None:
        return
    if not isinstance(reference, dict) or set(reference) - {'assetId', 'characterCardId', 'cameraMode', 'description'}:
        raise ValueError('动作参考绑定字段无效')
    if not isinstance(reference.get('assetId'), str) or not reference['assetId'].strip():
        raise ValueError('动作参考必须选择视频素材')
    if reference.get('cameraMode') not in ('follow_reference', 'use_shot_camera'):
        raise ValueError('请选择动作参考的摄像机模式')
    for key, maximum in (('characterCardId', 160), ('description', 4000)):
        if key in reference and (not isinstance(reference[key], str) or len(reference[key]) > maximum):
            raise ValueError('动作参考角色或说明无效')


def invalidated_nodes(rows, roots):
    from .collaboration_document import object_content
    affected=set(filter(None,roots))
    edges=[edge for row in rows if row['kind']=='graph' for edge in object_content(row)['edges']]
    while True:
        expanded=affected|{edge['target'] for edge in edges if edge['source'] in affected}
        if expanded==affected: return affected
        affected=expanded


def invalidate_content(content, node_ids, previous=None):
    value=copy.deepcopy(content)
    nodes=value.get('nodes', [value['node']] if 'node' in value else [])
    old_nodes={node['id']:node['data'] for node in (previous or content).get('nodes',
        [(previous or content)['node']] if 'node' in (previous or content) else [])}
    for node in nodes:
        if node['id'] not in node_ids: continue
        data=node['data'];old=old_nodes.get(node['id'],{})
        data['generation_revision']=max(int(data.get('generation_revision') or 0),int(old.get('generation_revision') or 0)+1)
        data['stale']=bool(data.get('assetId') or data.get('resultJob') or data.get('text'))
    return value


def compile_motion_input(document, node_id, kind, input_value, project_id, provider):
    result = copy.deepcopy(input_value)
    for key in ('generation_mode', 'motion_reference', 'reference_manifest', 'motion_compiler', 'motion_warnings'):
        result.pop(key, None)
    if kind != 'video':
        return result
    result['prompt'] = re.sub(re.escape(START) + r'.*?' + re.escape(END), '', str(result.get('prompt') or ''), flags=re.S).strip()
    shot = _shot_for_video_node(document, node_id) or {}
    validate_shot_reference(shot)
    reference = shot.get('motionReference')
    mode = resolve_generation_mode(document, shot)
    result['generation_mode'] = mode
    if mode['requested'] == 'legacy' and not reference:
        mode['actual'] = ('multimodal' if result.get('dialogue_audio') else
                          'first_last_frame' if result.get('end_asset_id') else
                          'first_frame' if result.get('asset_ids') else 'text_to_video')
        if not shot.get('videoReferenceMode') and not document.get('videoReferenceMode'):
            result.pop('generation_mode', None)  # Preserve pre-feature idempotency inputs.
        return result
    sources = result.get('image_reference_sources') or [
        {'type': 'asset', 'asset_id': aid} for aid in result.get('asset_ids', [])]
    if mode['requested'] != 'multimodal':
        if reference or result.get('dialogue_audio'):
            raise ValueError('严格首帧模式不能混入动作视频或对白音频，请明确切换为多模态参考')
        if len(sources) != 1 or bool(result.get('end_asset_id')) != (mode['requested'] == 'first_last_frame'):
            raise ValueError('严格首帧须恰好一张图；严格首尾帧还须尾帧，不会自动删除其他素材')
        if not (provider or {}).get('capabilities', {}).get('image_reference'):
            raise ValueError('所选模型未发布首帧能力')
        if result.get('end_asset_id') and not provider['capabilities'].get('end_frame'):
            raise ValueError('所选模型未发布严格尾帧能力')
        allowed = {item.get('asset_id') for item in sources} | {result.get('end_asset_id')}
        visual = (document.get('filmBible') or {}).get('visual') or {}
        for _, binding in _binding_rows(shot):
            primary = _primary_reference(visual.get('versions', {}).get(binding.get('versionId')) or {}) or {}
            if not primary.get('assetId') or primary['assetId'] not in allowed:
                raise ValueError('严格首帧不能额外提交视觉绑定，请调整模式或绑定，不会静默丢弃参考')
        manifest=[]
        for index, entry in enumerate([*sources, *([{'type':'asset','asset_id':result['end_asset_id']}] if result.get('end_asset_id') else [])]):
            item={'kind':'image','index':index+1,'purpose':'严格首帧' if index==0 else '严格尾帧'}
            if entry['type']=='asset':
                asset=common.assets_by_ids({'project_id':project_id},[entry['asset_id']])[0]
                if asset['kind']!='image': raise ValueError('首尾帧必须是图片素材')
                item.update(assetId=asset['id'],name=asset['name'])
            else: item.update(source=entry,name='待上游图片任务完成')
            manifest.append(item)
        result['reference_manifest']=manifest
        return result
    caps = capability(provider)
    if reference and not caps['video']:
        raise ValueError('所选平台模型未发布动作视频参考能力')
    manifest, ids, ordered, seen = [], [], [], set()

    def image(aid=None, source=None, **labels):
        entry = source or {'type': 'asset', 'asset_id': aid}
        if not isinstance(entry, dict) or entry.get('type') not in ('asset', 'upstream_node', 'upstream_job'):
            raise ValueError('图片参考来源无效')
        key = (entry['type'], entry.get('asset_id') or entry.get('node_id') or entry.get('job_id'))
        if not key[1]:
            return None
        if key not in seen:
            item = {'kind': 'image', 'index': len(ordered) + 1}
            if entry['type'] == 'asset':
                asset = common.assets_by_ids({'project_id': project_id}, [entry['asset_id']])[0]
                if asset['kind'] != 'image':
                    raise ValueError('视觉参考必须是图片')
                ids.append(asset['id']); item.update(assetId=asset['id'], name=asset['name'])
            else:
                item.update(source=entry, name='待上游图片任务完成')
            seen.add(key); ordered.append(entry); manifest.append(item)
        index = next(i + 1 for i, value in enumerate(ordered) if value == entry)
        manifest[index - 1].update(labels)
        return index

    nodes = {node['id']: node.get('data', {}) for node in document.get('nodes', [])}
    frame = nodes.get(shot.get('imageNode') or (shot.get('pipeline') or {}).get('imageNodeId'), {})
    # A queued image parent replaces its previous result, never silently append that old result.
    pending_nodes = {entry.get('node_id') for entry in sources if entry['type'] == 'upstream_node'}
    if (shot.get('imageNode') or (shot.get('pipeline') or {}).get('imageNodeId')) not in pending_nodes:
        image(frame.get('assetId'), purpose='起始构图参考（非严格首帧）')
    image(result.get('end_asset_id') or nodes.get(node_id,{}).get('end_asset_id'), purpose='结束构图参考（非严格尾帧）')
    for entry in sources:
        image(source=entry)
    visual = (document.get('filmBible') or {}).get('visual') or {}
    actors, image_lines = {}, []
    for group, binding in _binding_rows(shot):
        version = visual.get('versions', {}).get(binding.get('versionId')) or {}
        card = visual.get('cards', {}).get(version.get('cardId')) or {}
        if not card or card.get('deletedAt') or version.get('status') not in ('locked', 'deprecated'):
            raise ValueError('镜头视觉绑定须先确认主参考图')
        primary = _primary_reference(version) or {}
        if not primary.get('assetId'):
            raise ValueError('视觉绑定缺少主参考图')
        index = image(primary['assetId'], cardId=card['id'], versionId=version['id'], purpose=group)
        image_lines.append(f"@图片{index}：{card.get('name', card['id'])}的外观、服装及状态参考。")
        if group == 'character':
            for ancestor, _ in _version_chain(visual, version):
                actors[ancestor['id']] = index
    if len(ordered) > caps['max_images']:
        raise ValueError(f"完整参考图超过已发布的 {caps['max_images']} 张上限，不会截断")
    duration = max(4, math.ceil(float((result.get('parameters') or {}).get('duration') or result.get('shot_duration') or shot.get('duration') or 5)))
    if duration > caps['max_duration']:
        raise ValueError('镜头/对白时长超过当前多模态模型上限，请拆分镜头')
    if not {'duration','ratio'} <= (provider or {}).get('rules', {}).keys():
        raise ValueError('多模态模型须发布 duration 和 ratio 参数，以冻结实际时长与画幅')
    from .video_dialogue import _apply_duration, TIMING_MARKER
    timing=result['prompt'].split(TIMING_MARKER,1)
    _apply_duration(result,duration,float(shot.get('duration') or duration),provider['rules'])
    if len(timing)==2: result['prompt']+='\n\n'+TIMING_MARKER+timing[1]
    ratio=document.get('videoRatio') or document.get('ratio') or '16:9'
    result['ratio']=ratio
    result['parameters']={**result.get('parameters',{}),'ratio':ratio}
    frozen, warnings = None, []
    lines = [START, '生成模式：多模态参考。所有图片仅为构图、外观参考，不是严格首帧或尾帧约束。', *image_lines]
    for item in manifest:
        if '构图参考' in item.get('purpose', ''):
            lines.append(f"@图片{item['index']}：{item['purpose']}。")
    if reference:
        asset = common.assets_by_ids({'project_id': project_id}, [reference['assetId']])[0]
        metadata = inspect_motion(asset, caps)
        character = reference.get('characterCardId')
        if character and character not in actors:
            raise ValueError('动作执行角色必须是本镜头已绑定的角色或其基础角色')
        actor = f'@图片{actors[character]}中的角色' if character else '本镜头中符合动作描述的主体'
        lines += [f'{actor}参考@视频1的动作顺序、姿态、移动路径及节奏；不复制参考视频中的外观、场景或声音。',
                  '摄像机以@视频1为准，覆盖文字中冲突的运镜要求。' if reference['cameraMode'] == 'follow_reference'
                  else f"仅参考主体动作，摄像机以本镜头为准：{shot.get('camera') or '保持镜头提示词机位'}。",
                  reference.get('description', ''), '动作参考不是逐帧锁定，不得改变对白文字和音色。']
        if abs(metadata['duration'] - duration) > max(.1, 2 / metadata['fps']):
            warnings.append(f"动作参考 {metadata['duration']:.2f} 秒，提交 {duration} 秒；没有裁剪、变速或改写对白。")
        frozen = {**reference, 'media': metadata, 'silent_derivative': VERSION}
        manifest.append({'kind': 'video', 'index': 1, 'assetId': asset['id'], 'name': asset['name'],
                         'duration': metadata['duration'], 'audio': 'stripped'})
    audio = bool(result.get('dialogue_audio'))
    if audio:
        manifest.append({'kind': 'audio', 'index': 1, 'assetIds': result['dialogue_audio_asset_ids'],
                         'name': '固定对白时序参考', 'duration': duration})
        lines.append('严格使用@音频1的音色、情绪、语速和开口时序表演对白，不得改词或增加对白。')
    if not ordered and not reference and (not audio or not caps['audio_only']):
        raise ValueError('当前多模态模式需要图片或视频参考，不能仅文本或不受支持的仅音频提交')
    lines.append(END)
    result.update(prompt=result['prompt'] + '\n\n' + '\n'.join(filter(None, lines)), asset_ids=ids,
                  image_reference_sources=ordered, motion_reference=frozen, reference_manifest=manifest,
                  motion_warnings=warnings, motion_compiler={'version': VERSION, 'mode': 'multimodal',
                    'fingerprint': hashlib.sha256(s.dumps([mode, frozen, manifest]).encode()).hexdigest()})
    result.pop('end_asset_id', None)
    return result


def silent_motion_asset(job):
    frozen = job['input']['motion_reference']
    source = common.assets_by_ids(job, [frozen['assetId']])[0]
    path = (s.ASSETS / source['path']).resolve()
    if not path.is_relative_to(s.ASSETS.resolve()) or file_hash(path) != frozen['media']['sha256']:
        raise ValueError('动作参考文件在提交后变化，请重新提交')
    if not frozen['media']['has_audio']:
        return source
    # The existing single Worker owns creation; persisted derived metadata allows reuse after restart.
    with _DERIVATIVE_LOCK:
        with s.db() as c:
            rows = c.execute("""SELECT * FROM assets WHERE production_id=%s AND source='derived'
                AND metadata->>'motionDerivedFrom'=%s AND metadata->>'sourceSha256'=%s
                AND metadata->>'derivativeVersion'=%s
                AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='asset' AND d.item_id=assets.id)
                ORDER BY created""", (source['production_id'], source['id'], frozen['media']['sha256'], VERSION)).fetchall()
        for row in rows:
            candidate = s.unpack(row)
            target = (s.ASSETS / candidate['path']).resolve()
            if target.is_relative_to(s.ASSETS.resolve()) and target.is_file():
                return candidate
        output = s.DATA / (s.uid('motion-silent-') + '.mp4')
        try:
            run = subprocess.run([ffmpeg_executable(), '-v', 'error', '-y', '-i', str(path),
                '-map', '0:v:0', '-c:v', 'copy', '-an', '-movflags', '+faststart', str(output)],
                capture_output=True, timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if run.returncode:
                raise ValueError('动作参考静音副本生成失败')
            metadata = probe(output)
            if metadata.get('has_audio') or abs(metadata['duration'] - frozen['media']['duration']) > max(.1, 2 / frozen['media']['fps']):
                raise ValueError('动作参考静音副本校验失败')
            derived = common.register(job, output, '动作参考·静音·' + source['name'], category='reference', asset_source='derived')
            with s.db() as c:
                c.execute('UPDATE assets SET metadata=metadata||%s::jsonb WHERE id=%s',
                    (s.dumps({'motionDerivedFrom': source['id'], 'sourceSha256': frozen['media']['sha256'],
                              'derivativeVersion': VERSION}), derived['id']))
            return common.assets_by_ids(job, [derived['id']])[0]
        finally:
            output.unlink(missing_ok=True)
