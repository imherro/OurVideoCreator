"""Four explicit setup cards over the existing versioned provider/model store.

Public defaults follow MyVideoCreator 564dd22. No key or live account config is
copied. A card save is one PostgreSQL transaction, including RunningHub's two
explicit origins; existing models and historical credentials remain intact.
"""
from copy import deepcopy
import hashlib
import json

from fastapi import HTTPException

from . import platform_models as models, model_validation as validation, store as s


def _model(key, name, kind, upstream, defaults, rules, capabilities=None, primary=True, service=0):
    return {'key': key, 'kind': kind, 'service': service, 'primary': primary,
            'definition': {'name': name, 'upstream_model': upstream, 'defaults': defaults,
                           'rules': rules, 'capabilities': capabilities or {}}}


def _video(key, name, upstream, provider, primary=True):
    newer = '2.5' in upstream or '2-5' in upstream
    caps = {'image_reference': True, 'max_references': 30 if newer else 9,
            'end_frame': provider != 'hc_atom', 'audio_reference': True,
            'multimodal_reference': True, 'video_reference': True,
            'audio_only_reference': newer, 'voice_sample_reference': True,
            'max_audio_references': 10 if newer else 3}
    defaults = {'duration': 5, 'ratio': '16:9'}
    rules = {'duration': {'type': 'integer', 'min': 4, 'max': 30 if newer else 15},
             'ratio': {'type': 'string', 'enum': ['16:9', '9:16', '1:1', '4:3', '3:4', '21:9']}}
    if provider != 'hc_atom':
        defaults.update(resolution='720p', generate_audio=True)
        rules.update(resolution={'type': 'string', 'enum': ['480p', '720p', '1080p']},
                     generate_audio={'type': 'boolean'})
    return _model(key, name, 'video', upstream, defaults, rules, caps, primary)


def _text(key, name, upstream, service=0):
    return _model(key, name, 'text', upstream, {'max_tokens': 4096, 'temperature': 0.6},
                  {'max_tokens': {'type': 'integer', 'min': 1, 'max': 32000},
                   'temperature': {'type': 'number', 'min': 0, 'max': 2}}, service=service)


PRESETS = [
    {'id': 'runninghub', 'name': 'RunningHub', 'description': '一个 Key 配置文本、图片和视频。',
     'services': [{'name': 'RunningHub 媒体', 'type': 'runninghub', 'url': 'https://www.runninghub.ai'},
                  {'name': 'RunningHub 文本', 'type': 'runninghub', 'url': 'https://llm.runninghub.ai/v1'}],
     'models': [
         _text('text', 'RunningHub · Doubao Seed 2.1 Pro', 'bytedance/doubao-seed-2.1-pro', 1),
         _model('image', 'RunningHub · Seedream 5 Pro', 'image', 'seedream-v5-pro',
                {'size': '1024x1024', 'resolution': '2k'},
                {'size': {'type': 'string', 'max_length': 30},
                 'resolution': {'type': 'string', 'enum': ['2k', '4k']}},
                {'image_reference': True, 'max_references': 10}),
         _video('video', 'RunningHub · Seedance 2.5', 'bytedance/seedance-2.5-token', 'runninghub')]},
    {'id': 'hc', 'name': '幻场 AI', 'description': '默认提供 Seedance 2.5，保留 Seedance 2.0 可选。',
     'services': [{'name': '幻场 AI', 'type': 'hc_atom', 'url': 'https://api-aigc.fzyinghe.com'}],
     'models': [_video('video', '幻场 AI · Seedance 2.5', 'doubao-seedance-2.5', 'hc_atom'),
                _video('video-2-0', '幻场 AI · Seedance 2.0', 'doubao-seedance-2.0', 'hc_atom', False)]},
    {'id': 'ark', 'name': '火山引擎', 'description': '火山方舟 ARK Key，用于文本、图片和视频。',
     'services': [{'name': '火山引擎 / 火山方舟', 'type': 'volcengine_ark',
                   'url': 'https://ark.cn-beijing.volces.com/api/v3'}],
     'models': [
         _text('text', '火山 · Doubao Seed 2.1 Pro', 'doubao-seed-2-1-pro-260628'),
         _model('image', '火山 · Seedream 5 Pro', 'image', 'doubao-seedream-5-0-pro-260628',
                {'size': '2K', 'watermark': False},
                {'size': {'type': 'string', 'max_length': 30}, 'watermark': {'type': 'boolean'}},
                {'image_reference': True, 'max_references': 10}),
         _video('video', '火山 · Seedance 2.5', 'doubao-seedance-2-5-260628', 'volcengine_ark'),
         _video('video-2-0', '火山 · Seedance 2.0', 'doubao-seedance-2-0-260128', 'volcengine_ark', False)]},
    {'id': 'speech', 'name': '豆包语音', 'description': '独立的 Speech API Key，与火山方舟 Key 分开填写。',
     'services': [{'name': '豆包语音', 'type': 'volcengine_speech',
                   'url': 'https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse',
                   'options': {'resource_id': 'seed-tts-2.0'}}],
     'models': [_model('audio', '豆包语音 · Seed TTS 2.0', 'audio', 'seed-tts-2.0',
                       {'voice_type': 'zh_female_vv_uranus_bigtts', 'format': 'mp3',
                        'sample_rate': 24000, 'speech_rate': 0, 'loudness_rate': 0,
                        'emotion': '', 'context_texts': []},
                       {'voice_type': {'type': 'string', 'enum': ['zh_female_vv_uranus_bigtts']},
                        'format': {'type': 'string', 'enum': ['mp3', 'ogg_opus']},
                        'sample_rate': {'type': 'integer', 'enum': [8000, 16000, 22050, 24000, 32000, 44100, 48000]},
                        'speech_rate': {'type': 'integer', 'min': -50, 'max': 100},
                        'loudness_rate': {'type': 'integer', 'min': -50, 'max': 100},
                        'emotion': {'type': 'string', 'max_length': 500},
                        'context_texts': {'type': 'strings', 'max_length': 500}})]},
]


def _state(c, preset):
    providers = [models._provider_view(c, row) for row in c.execute('SELECT * FROM model_providers')]
    all_models = [models._model_view(c, row, private=True) for row in c.execute('SELECT * FROM model_catalog')]
    defaults = {row['kind']: row['model_id'] for row in c.execute('SELECT * FROM model_defaults')}
    services, entries, conflicts = [], [], []
    for index, template in enumerate(preset['services']):
        matches = [p for p in providers if p['config']['type'] == template['type']
                   and p['config']['url'].rstrip('/') == template['url'].rstrip('/')]
        provider_id = f"preset-{preset['id']}-{index}"
        if len(matches) > 1:
            conflicts.append('发现多个相同地址的服务，请在高级配置中核对后使用快捷配置。')
        current = matches[0] if len(matches) == 1 else None
        if not current and any(p['id'] == provider_id for p in providers):
            conflicts.append('快捷服务已被修改为其他地址，请使用高级配置保留并编辑。')
        services.append({'id': current['id'] if current else provider_id, 'revision': current['revision'] if current else 0,
                         'current': current, 'template': template})
    for template in preset['models']:
        pid = services[template['service']]['id']
        matches = [m for m in all_models if m['provider_id'] == pid and m['kind'] == template['kind']
                   and m['definition']['upstream_model'] == template['definition']['upstream_model']]
        model_id = f"preset-{preset['id']}-{template['key']}"
        if len(matches) > 1:
            conflicts.append('发现多个相同模型，请使用高级配置核对。')
        current = matches[0] if len(matches) == 1 else None
        if not current and any(m['id'] == model_id for m in all_models):
            conflicts.append('快捷模型已被自定义，请使用高级配置。')
        entries.append({'id': current['id'] if current else model_id, 'revision': current['revision'] if current else 0,
                        'provider_id': pid, 'current': current, 'template': template})
    kinds = {m['kind'] for m in preset['models']}
    stamp = {'providers': [(v['id'], v['revision']) for v in services],
             'models': [(v['id'], v['revision']) for v in entries],
             'defaults': {k: defaults.get(k) for k in sorted(kinds)}}
    revision = hashlib.sha256(json.dumps(stamp, sort_keys=True).encode()).hexdigest()
    return services, entries, defaults, list(dict.fromkeys(conflicts)), revision


def _view(c, preset):
    services, entries, defaults, conflicts, revision = _state(c, preset)
    return {'id': preset['id'], 'name': preset['name'], 'description': preset['description'],
            'revision': revision, 'conflicts': conflicts,
            'configured': all(v['current'] and v['current']['api_key_set'] for v in services),
            'public_base_url': next((v['current']['config']['options'].get('public_base_url', '')
                                    for v in services if v['current']), ''),
            'models': [{'id': v['id'], 'kind': v['template']['kind'],
                        'name': (v['current'] or {}).get('name', v['template']['definition']['name']),
                        'upstream_model': v['template']['definition']['upstream_model'],
                        'primary': v['template']['primary'],
                        'configured': bool(v['current']),
                        'published': bool(v['current'] and v['current']['published'] and v['current']['enabled']),
                        'is_default': defaults.get(v['template']['kind']) == v['id']} for v in entries]}


def catalog():
    models._admin()
    with s.db() as c:
        return {'presets': [_view(c, preset) for preset in PRESETS]}


def save(preset_id, body):
    models._admin()
    validation._object(body, {'revision', 'api_key', 'use_defaults', 'public_base_url'}, '快捷配置')
    preset = next((p for p in PRESETS if p['id'] == preset_id), None)
    if preset is None:
        raise HTTPException(404, '供应商预设不存在')
    use_defaults = models._bool(body, 'use_defaults', False)
    key = body.get('api_key')
    if 'api_key' in body and (not isinstance(key, str) or not key.strip()):
        raise ValueError('请填写 API Key；更新时留空表示保留原 Key')
    if 'public_base_url' in body and (preset_id != 'hc' or not isinstance(body['public_base_url'], str)):
        raise ValueError('素材访问地址格式无效')
    with s.db() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)', (0x4F56435F4D444C31,))
        services, entries, defaults, conflicts, revision = _state(c, preset)
        if conflicts:
            raise HTTPException(409, conflicts[0])
        if body.get('revision') != revision:
            raise HTTPException(409, '配置已被其他页面修改，请刷新后重试；输入的 Key 仍保留')
        for item in services:
            old, template = item['current'], item['template']
            config = deepcopy(old['config'] if old else {k: v for k, v in template.items() if k != 'name'})
            config.setdefault('auth_mode', 'api_key')
            config.setdefault('options', {})
            if 'public_base_url' in body:
                value = body['public_base_url'].strip()
                if value:
                    config['options']['public_base_url'] = value
                else:
                    config['options'].pop('public_base_url', None)
            change = {'revision': item['revision'], 'name': old['name'] if old else template['name'],
                      'enabled': True, 'config': config}
            if 'api_key' in body:
                change['api_key'] = key.strip()
            models.save_provider(item['id'], change, connection=c)
        for item in entries:
            old, template = item['current'], item['template']
            make_default = use_defaults and template['primary']
            if old and not make_default:
                continue  # A key rotation must not reset custom model definitions or publication.
            change = {'revision': item['revision'], 'provider_id': item['provider_id'],
                      'kind': template['kind'], 'definition': old['definition'] if old else template['definition'],
                      'published': True, 'enabled': True,
                      'default': make_default or defaults.get(template['kind']) == item['id']}
            models.save_model(item['id'], change, connection=c)
        return {'preset': _view(c, preset), 'message': 'Key 已安全保存，默认模型已配置。尚未验证供应商鉴权，未发起生成。'}
