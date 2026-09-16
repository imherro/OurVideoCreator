"""Platform model selection for project and visual-card defaults."""
from __future__ import annotations

KINDS = ('text', 'image', 'video')


def default_platform_policy(models):
    return {kind: next(({'model_id': model['id']} for model in models
                        if model.get('kind') == kind and model.get('is_default')), None)
            for kind in KINDS}


def validate_generation_policy(policy, models, allow_missing=False):
    if not isinstance(policy, dict) or set(policy) - set(KINDS):
        raise ValueError('项目生成策略必须是文本/图片/视频平台模型对象')
    configured = {model['id']: model for model in models}
    result = {}
    for kind in KINDS:
        target = policy.get(kind)
        if target is None:
            result[kind] = None
            continue
        if (not isinstance(target, dict) or set(target) != {'model_id'}
                or not isinstance(target.get('model_id'), str) or not target['model_id']):
            raise ValueError('项目默认模型只接受平台 model_id')
        model = configured.get(target['model_id'])
        if model is None and not allow_missing:
            raise ValueError('平台模型已停用或未发布，请重新选择；不会自动切换')
        if model is not None and model['kind'] != kind:
            raise ValueError('项目默认模型用途不匹配')
        result[kind] = {'model_id': target['model_id']}
    return result


def resolve_generation_target(kind, override, project_policy, models, local_models=None):
    if kind not in KINDS:
        raise ValueError('不支持的生成类型')
    candidate, source = None, 'project'
    if isinstance(override, dict) and override.get('mode') == 'override':
        candidate, source = {'model_id': override.get('model_id')}, 'override'
    elif isinstance(project_policy, dict):
        candidate = project_policy.get(kind)
    if not candidate:
        raise ValueError(f'尚未为项目配置默认 {kind} 平台模型；系统不会自动选择其他付费模型')
    validated = validate_generation_policy({kind: candidate}, models)[kind]
    return {**validated, 'source': source}
