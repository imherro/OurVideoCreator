"""Local image specification shared by preview, admission and replay.

Only platform-published controls can reach an adapter. Templates/credentials
remain private; the public specification describes requested, not output, pixels.
"""
import json
import math
import re
import secrets

from . import model_validation as validation


def resolve(definition, submitted, document, node_id, config, settings=None, *, freeze=False, frozen_seed=None):
    settings = {} if settings is None else settings
    validation._object(settings, {'sizeMode', 'size', 'seed'}, '图像生成设置')
    mode = settings.get('sizeMode', 'project')
    rules = definition['rules']
    provider_type = config['type']
    workflow = json.dumps(config.get('options', {}).get('workflow', {}))
    native = provider_type in {'maestro', 'comfy'}
    pixel_rule = rules.get('resolution', {})
    size_supported = native and pixel_rule.get('type') == 'string' and (
        provider_type == 'maestro' or all('{{' + name + '}}' in workflow for name in ('width', 'height')))
    seed_supported = native and rules.get('seed', {}).get('type') == 'integer' and (
        provider_type == 'maestro' or '{{seed}}' in workflow)
    node = next((n for n in document.get('nodes', []) if n.get('id') == node_id), {})
    ratio = '2:1' if (node.get('data') or {}).get('image_purpose') == 'panorama' else document.get('ratio', '16:9')
    if ratio not in {'21:9', '16:9', '4:3', '1:1', '3:4', '9:16', '2:1'}:
        raise ValueError('请先设置有效的项目画幅')
    if mode not in ('project', 'video', 'custom') or (mode != 'project' and not size_supported):
        raise ValueError('当前平台模型未开放此尺寸选项，请选择跟随项目画幅')
    size = None
    a, b = map(int, ratio.split(':'))
    if mode == 'video':
        short = {'480p':480, '720p':720, '1080p':1080}.get(document.get('videoResolution'), 720)
        w, h = (round(short * a / b), short) if a >= b else (short, round(short * b / a))
        size = f'{w // 8 * 8}x{h // 8 * 8}'
    elif mode == 'custom':
        size = settings.get('size', '')
        if not isinstance(size, str) or not re.fullmatch(r'\d{3,4}x\d{3,4}', size):
            raise ValueError('图像尺寸请输入宽x高，例如1280x720')
        w, h = map(int, size.split('x'))
        if not all(256 <= n <= 4096 and n % 8 == 0 for n in (w, h)) or abs(w / h / (a / b) - 1) > .02:
            raise ValueError('自定义尺寸须与项目画幅一致，宽高为256–4096且是8的倍数')
    if size is not None:
        # An explicit override must be accepted exactly, never replaced by a
        # different same-aspect default when the admin enum excludes it.
        validation.validate_parameter(size, pixel_rule)
        if 'size' in rules:
            validation.validate_parameter(size, rules['size'])
    submitted = dict(submitted)
    if 'seed' in settings:
        seed = settings['seed']
        if type(seed) is not int or not -1 <= seed <= 2147483647:
            raise ValueError('随机种子应为-1或0–2147483647的整数')
        if not seed_supported and seed != -1:
            raise ValueError('当前平台模型未实现固定随机种子')
        if seed_supported:
            submitted['seed'] = seed
    parameters = validation.shot_parameters(definition, submitted, 'image', document, node_id, image_size=size)
    if not seed_supported and parameters.get('seed', -1) != -1:
        raise ValueError('当前平台模型未实现固定随机种子，请移除固定种子参数')
    seed = parameters.get('seed') if seed_supported else None
    if seed_supported and seed is not None and (type(seed) is not int or not -1 <= seed <= 2147483647):
        raise ValueError('随机种子应为-1或0–2147483647的整数')
    if seed_supported and seed == -1:
        rule = rules['seed']
        if 'enum' in rule:
            choices = [v for v in rule['enum'] if type(v) is int and 0 <= v <= 2147483647]
            if not choices:
                raise ValueError('平台种子规则没有可冻结的非负整数')
        else:
            low, high = math.ceil(max(0, rule.get('min', 0))), math.floor(min(2147483647, rule.get('max', 2147483647)))
            if low > high:
                raise ValueError('平台种子规则没有可冻结的非负整数')
        if freeze:
            seed = frozen_seed if frozen_seed is not None else (
                secrets.choice(choices) if 'enum' in rule else secrets.randbelow(high - low + 1) + low)
            validation.validate_parameter(seed, rule)
            parameters['seed'] = seed
    # Native adapters consume resolution; cloud image adapters consume size.
    pixel_field = 'resolution' if native else 'size'
    pixels = parameters.get(pixel_field)
    if native and pixels is not None and not re.fullmatch(r'\d+x\d+', str(pixels)):
        raise ValueError('当前原生图像适配器的resolution必须是宽x高像素尺寸')
    if not isinstance(pixels, str) or not re.fullmatch(r'\d+x\d+', pixels):
        pixels = None
    options = [{'value':'project', 'label':'跟随项目画幅 · 推荐尺寸'}]
    if size_supported:
        options += [{'value':'video', 'label':'与项目视频像素一致'}, {'value':'custom', 'label':'自定义像素尺寸'}]
    spec = {'version':'platform-image-settings/v1', 'sizeMode':mode, 'ratio':ratio,
            'size':pixels, 'seedSupported':seed_supported, 'seed':seed,
            'parameters':parameters, 'sizeOptions':options,
            'sizeNote': '请求规格不保证供应商实际输出像素；未发布尺寸控制时沿用平台配置。'}
    if provider_type == 'runninghub':
        spec['sizeNote'] = 'RunningHub同时提交尺寸与质量档位，实际输出像素以生成结果为准。'
    return parameters, spec
