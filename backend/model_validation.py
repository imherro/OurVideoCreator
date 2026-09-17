"""Explicit model schema and parameter checks, not a general rule language."""
from __future__ import annotations

import copy
import math
import re
from urllib.parse import urlsplit

from .provider_egress import validate_url

PROVIDER_KINDS = {
    'openai': {'text', 'image'}, 'volcengine_ark': {'text', 'image', 'video'},
    'hc_atom': {'text', 'image', 'video'}, 'runninghub': {'text', 'image', 'video'},
    'volcengine_speech': {'audio'}, 'replicate': {'text', 'image', 'video'},
    'minimax': {'video'}, 'comfy': {'image', 'video'}, 'maestro': {'image', 'video'},
    'video_api': {'video'},
}
PARAMETERS = {
    'max_tokens', 'temperature', 'top_p', 'seed', 'duration', 'resolution', 'size',
    'aspect_ratio', 'ratio', 'n', 'count', 'frames', 'fps', 'quality', 'steps',
    'guidance_scale', 'negative_prompt', 'watermark', 'generate_audio',
    'prompt_optimizer', 'format', 'sample_rate', 'speech_rate', 'loudness_rate',
    'emotion', 'context_texts', 'voice_type',
}
_PRIVATE = {
    'provider', 'providerid', 'providerconfig', 'providerconfiguration', 'providers',
    'apikey', 'key', 'token', 'accesstoken', 'authorization', 'headers', 'header',
    'cookie', 'credentials', 'credential', 'credentialversionid', 'configversionid',
    'modelversionid', 'url', 'baseurl', 'endpoint', 'endpointurl', 'upstreammodel',
    'upstreammodelid', 'model', 'models', 'secret', 'password', 'auth',
}


def reject_private_overrides(value):
    """Reject hidden nested selectors without echoing submitted names/values."""
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r'[^a-z0-9]', '', str(key).lower())
            if normalized == 'url' and isinstance(child,str) and re.fullmatch(r'/api/assets/[A-Za-z0-9_-]+/file',child):
                continue
            if (normalized in _PRIVATE or normalized.endswith(('apikey', 'baseurl', 'endpointurl'))
                    or normalized.startswith(('authorization', 'xapikey'))):
                raise ValueError('不得提交供应商、凭证、地址、headers 或上游模型覆盖；请选择平台 model_id')
            reject_private_overrides(child)
    elif isinstance(value, list):
        for child in value:
            reject_private_overrides(child)


def _object(value, allowed, label):
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError(label + '字段无效')


def _string(value, label, maximum=200):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(label + '格式无效')
    return value.strip()


def supported_protocol(config, kind=None):
    """Reject combinations not implemented by the existing adapters, also on restore."""
    provider_type = config.get('type')
    if provider_type not in PROVIDER_KINDS:
        raise ValueError('不支持的 Provider 类型')
    if provider_type in {'comfy', 'maestro'} and config.get('auth_mode', 'api_key') != 'none':
        raise ValueError('当前 Maestro/Comfy 适配器仅支持无认证 API，不支持 API Key 模式')
    if kind is not None and kind not in PROVIDER_KINDS[provider_type]:
        raise ValueError('Provider 不支持该模型用途')


def provider_config(body):
    _object(body, {'type', 'url', 'options', 'auth_mode'}, 'Provider 配置')
    provider_type = body.get('type')
    if provider_type not in PROVIDER_KINDS:
        raise ValueError('不支持的 Provider 类型')
    url = _string(body.get('url'), '服务地址', 2048).rstrip('/')
    validate_url(url)
    if urlsplit(url).query:
        raise ValueError('服务基础地址不能包含查询参数；凭证必须通过专用字段保存')
    auth_mode = body.get('auth_mode', 'api_key')
    if auth_mode not in {'api_key', 'none'}:
        raise ValueError('认证方式无效')
    if auth_mode == 'none' and provider_type not in {'openai', 'comfy', 'maestro', 'video_api'}:
        raise ValueError('该适配器要求 API Key')
    supported_protocol({'type': provider_type, 'auth_mode': auth_mode})
    options = copy.deepcopy(body.get('options', {}))
    _object(options, {'structured', 'resource_id', 'public_base_url', 'asset_group_id',
                      'parameters', 'workflow', 'request_defaults', 'submit_path', 'status_path'}, '协议选项')
    # Admin protocol templates may contain model names and literal media fields,
    # but are not an alternative credential/header store.
    def check_options(value):
        if isinstance(value, dict):
            for key, child in value.items():
                name = re.sub(r'[^a-z0-9]', '', str(key).lower())
                if name in {'apikey', 'key', 'token', 'accesstoken', 'authorization', 'headers',
                            'password', 'secret', 'credential', 'credentials', 'cookie'}:
                    raise ValueError('协议选项不能包含凭证或认证 headers')
                check_options(child)
        elif isinstance(value, list):
            for child in value:
                check_options(child)
        elif isinstance(value, str) and value.startswith(('http:', 'https:')):
            validate_url(value)
    check_options(options)
    for name in ('submit_path', 'status_path'):
        if name in options:
            path = options[name]
            if not isinstance(path, str) or not path.startswith('/') or path.startswith('//') or any(c in path for c in '\\?#'):
                raise ValueError('协议路径必须是服务内的绝对路径')
    for name in ('parameters', 'workflow', 'request_defaults'):
        if name in options and not isinstance(options[name], dict):
            raise ValueError('协议模板必须是对象')
    return {'type': provider_type, 'url': url, 'auth_mode': auth_mode, 'options': options}


def validate_rule(rule):
    _object(rule, {'type', 'min', 'max', 'enum', 'max_length'}, '参数规则')
    if rule.get('type') not in {'integer', 'number', 'string', 'boolean', 'strings'}:
        raise ValueError('参数规则类型无效')
    for name in ('min', 'max'):
        if name in rule and (type(rule[name]) not in (int, float) or not math.isfinite(rule[name])):
            raise ValueError('参数范围必须为有限数值')
    if rule.get('min', -math.inf) > rule.get('max', math.inf):
        raise ValueError('参数下限不能大于上限')
    if 'max_length' in rule and (type(rule['max_length']) is not int or not 1 <= rule['max_length'] <= 24000):
        raise ValueError('参数长度上限无效')
    if 'enum' in rule:
        if not isinstance(rule['enum'], list) or not 1 <= len(rule['enum']) <= 100:
            raise ValueError('参数枚举无效')
        for item in rule['enum']:
            validate_parameter(item, {k: v for k, v in rule.items() if k != 'enum'})


def validate_parameter(value, rule):
    kind = rule['type']
    valid = ((kind == 'integer' and type(value) is int) or
             (kind == 'number' and type(value) in (int, float) and math.isfinite(value)) or
             (kind == 'string' and isinstance(value, str)) or
             (kind == 'boolean' and type(value) is bool) or
             (kind == 'strings' and isinstance(value, list) and len(value) <= 20 and
              all(isinstance(item, str) and len(item) <= rule.get('max_length', 2000) for item in value)))
    if not valid:
        raise ValueError('生成参数类型不匹配')
    if kind in {'integer', 'number'} and not rule.get('min', -math.inf) <= value <= rule.get('max', math.inf):
        raise ValueError('生成参数超出允许范围')
    if kind == 'string' and len(value) > rule.get('max_length', 2000):
        raise ValueError('生成参数超过允许长度')
    if 'enum' in rule and value not in rule['enum']:
        raise ValueError('生成参数不在允许枚举中')


def model_definition(body, config, kind):
    _object(body, {'name', 'upstream_model', 'capabilities', 'defaults', 'rules'}, '模型定义')
    supported_protocol(config, kind)
    value = copy.deepcopy(body)
    value['name'] = _string(body.get('name'), '模型名称', 100)
    value['upstream_model'] = _string(body.get('upstream_model'), '上游模型标识', 500)
    if config['type']=='minimax' and value['upstream_model']!='MiniMax-Hailuo-2.3':
        raise ValueError('当前 MiniMax 原生适配器仅接通 MiniMax-Hailuo-2.3')
    caps = value.setdefault('capabilities', {})
    _object(caps, {'image_reference', 'end_frame', 'audio_reference', 'max_references',
                  'requires_reference', 'max_prompt_length',
                  'fps', 'min_frames', 'frame_step', 'max_frames'}, '模型能力')
    for name in ('image_reference', 'end_frame', 'audio_reference', 'requires_reference'):
        if name in caps and type(caps[name]) is not bool:
            raise ValueError('模型能力必须为布尔值')
    for name, ceiling in (('max_references', 30), ('max_prompt_length', 240000)):
        if name in caps and (type(caps[name]) is not int or not 0 <= caps[name] <= ceiling):
            raise ValueError('模型能力上限无效')
    timing = {'fps', 'min_frames', 'frame_step', 'max_frames'}
    if timing.intersection(caps):
        if kind != 'video' or not timing.issubset(caps):
            raise ValueError('视频帧数能力必须完整声明')
        if any(type(caps[name]) is not int or not 1 <= caps[name] <= 10000 for name in timing):
            raise ValueError('视频帧数能力无效')
        if caps['fps'] > 240 or caps['max_frames'] < caps['min_frames']:
            raise ValueError('视频帧数范围无效')
    if kind not in {'image', 'video'} and any(caps.get(name) for name in ('image_reference', 'end_frame', 'requires_reference')):
        raise ValueError('该用途不支持图像参考能力')
    if caps.get('end_frame') and (kind != 'video' or config['type'] not in {'volcengine_ark', 'runninghub', 'maestro'}):
        raise ValueError('当前适配器未接通尾帧协议')
    if caps.get('audio_reference') and (kind != 'video' or config['type'] not in {'volcengine_ark', 'runninghub'}):
        raise ValueError('当前适配器未接通参考音频协议')
    if caps.get('image_reference') and config['type'] in {'openai','video_api'}:
        raise ValueError('当前适配器未接通参考图协议')
    if caps.get('requires_reference') and not caps.get('image_reference'):
        raise ValueError('必须参考图的模型也需要声明参考图能力')
    if caps.get('end_frame') and not caps.get('image_reference'):
        raise ValueError('尾帧模式必须声明首帧参考能力')
    limit = ({'volcengine_ark':10,'hc_atom':10,'runninghub':10,'comfy':1}.get(config['type'],30)
             if kind=='image' else {'volcengine_ark':1,'hc_atom':1,'runninghub':30,'comfy':1,'maestro':1,'minimax':1}.get(config['type'],30))
    if caps.get('max_references',1)>limit:
        raise ValueError('参考图数量超过当前适配器已接通的上限')
    rules = value.setdefault('rules', {})
    defaults = value.setdefault('defaults', {})
    _object(rules, PARAMETERS, '允许参数')
    _object(defaults, set(rules), '默认参数')
    if kind=='audio' and config['type']=='volcengine_speech' and not rules.get('voice_type',{}).get('enum'):
        raise ValueError('语音模型必须发布 voice_type 允许音色枚举')
    if kind == 'audio' and config['type'] == 'volcengine_speech':
        voices = rules['voice_type']['enum']
        if not isinstance(voices, list) or any(not isinstance(v, str) or not v or v != v.strip() for v in voices):
            raise ValueError('音色枚举必须是非空且无首尾空白的音色 ID，不能触发协议回退')
    for name, rule in rules.items():
        validate_rule(rule)
        if name in defaults:
            validate_parameter(defaults[name], rule)
    if timing.intersection(caps):
        if rules.get('frames', {}).get('type') != 'integer':
            raise ValueError('视频帧数能力需要 frames 整数规则')
        for count in (caps['min_frames'], caps['max_frames']):
            validate_parameter(count, rules['frames'])
    return value


def image_parameters(definition, result, document, node_id):
    """Derive only published controls, including images outside shot objects."""
    ratio = document.get('ratio')
    node = next((n for n in document.get('nodes', []) if n.get('id') == node_id), {})
    # An explicit, saved panorama node is not an episode opening frame. Do not
    # infer this from prompt text or from caller-supplied submission metadata.
    if (node.get('data') or {}).get('image_purpose') == 'panorama':
        ratio = '2:1'
    recommended = {'21:9':'2048x864', '16:9':'2048x1152', '4:3':'2048x1536',
                   '1:1':'2048x2048', '3:4':'1536x2048', '9:16':'1152x2048', '2:1':'1024x512'}.get(ratio)
    if not recommended:
        return result
    rules = definition['rules']
    for name in ('ratio', 'aspect_ratio'):
        if name in rules:
            try: validate_parameter(ratio, rules[name])
            except ValueError as exc: raise ValueError('平台模型不支持当前项目画幅，请调整已发布模型或项目规格') from exc
            result[name] = ratio
    for name in ('size', 'resolution'):
        rule = rules.get(name)
        if not rule or rule['type'] != 'string':
            continue
        values = rule.get('enum', [])
        # resolution may mean a quality tier (2k/4k), not width x height.
        if name == 'resolution' and (re.fullmatch(r'\d+(?:k|p)', str(result.get(name, '')), re.IGNORECASE)
                or (values and not any(re.fullmatch(r'\d+x\d+', str(v)) for v in values))):
            continue
        try:
            validate_parameter(recommended, rule)
            result[name] = recommended
            continue
        except ValueError:
            pass
        current = str(result.get(name, ''))
        match = re.fullmatch(r'(\d+)x(\d+)', current)
        a, b = map(int, ratio.split(':'))
        if match and int(match[2]) > 0 and abs(int(match[1]) / int(match[2]) / (a / b) - 1) <= .02:
            continue  # Keep an already validated alternative within platform limits.
        raise ValueError('平台允许的图像尺寸与项目画幅不一致；请调整模型尺寸规则或项目规格')
    return result


def shot_parameters(definition, submitted, kind, document, node_id, *, complete=True):
    """Recompute linked-shot controls from canonical state and frozen model rules."""
    # Canonical shot controls may fill missing fields. Require completeness only
    # after that derivation, before freezing or making any external request.
    result = parameters(definition, submitted, complete=False)
    if kind == 'image':
        result = image_parameters(definition, result, document, node_id)
    shot = next((item for item in document.get('shots', [])
                 if item.get(kind + 'Node') == node_id
                 or (item.get('pipeline') or {}).get(kind + 'NodeId') == node_id), None)
    if not shot:
        return parameters(definition, result, complete=complete)
    caps, rules = definition['capabilities'], definition['rules']
    if kind == 'video' and 'fps' in caps and float(shot.get('duration', 0)) > 0:
        minimum, step, maximum = caps['min_frames'], caps['frame_step'], caps['max_frames']
        fixed = document.get('videoDuration', -1)
        duration = fixed if isinstance(fixed, (int,float)) and 4 <= fixed <= 30 else float(shot['duration'])
        count = minimum + math.floor((duration * caps['fps'] - minimum) / step + .5) * step
        result['frames'] = min(minimum + (maximum - minimum) // step * step, max(minimum, count))
    return parameters(definition, result, complete=complete)


def parameters(definition, submitted, *, complete=True):
    _object(submitted, set(definition['rules']), '生成参数')
    result = {**definition['defaults'], **submitted}
    for name, value in result.items():
        validate_parameter(value, definition['rules'][name])
    missing = set(definition['rules']) - set(result)
    if complete and missing:
        raise ValueError('缺少平台受限参数，请填写或由管理员设置合法默认值：' + ', '.join(sorted(missing)))
    return result
