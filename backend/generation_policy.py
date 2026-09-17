"""Platform model selection for project and visual-card defaults."""
from __future__ import annotations

KINDS = ('text', 'image', 'video')
MODEL_POOL_KINDS = KINDS + ('audio',)


def default_model_pool(models):
    """Freeze the public platform IDs available when a Production is created."""
    return {kind: [{'model_id': model['id']} for model in models if model.get('kind') == kind]
            for kind in MODEL_POOL_KINDS}


def validate_model_pool(pool, models, allow_missing=False):
    if pool is None:
        return None
    if not isinstance(pool, dict) or set(pool) - set(MODEL_POOL_KINDS):
        raise ValueError('项目模型范围必须是文本、图片、视频和音频平台模型对象')
    configured = {model['id']: model for model in models}
    result = {}
    for kind in MODEL_POOL_KINDS:
        values = pool.get(kind, [])
        if not isinstance(values, list):
            raise ValueError(f'项目可用 {kind} 模型必须是数组')
        targets, seen = [], set()
        for target in values:
            if (not isinstance(target, dict) or set(target) != {'model_id'}
                    or not isinstance(target.get('model_id'), str) or not target['model_id'].strip()):
                raise ValueError('项目模型范围只接受平台 model_id')
            model_id = target['model_id'].strip()
            if model_id in seen:
                continue
            model = configured.get(model_id)
            if model is None and not allow_missing:
                raise ValueError('项目模型范围包含已停用或未发布的平台模型')
            if model is not None and model.get('kind') != kind:
                raise ValueError('项目模型范围中的模型用途不匹配')
            targets.append({'model_id': model_id})
            seen.add(model_id)
        result[kind] = targets
    return result


def validate_policy_in_pool(policy, pool):
    # Legacy Productions have no modelPool and retain their previous global
    # catalog behavior. New Productions always persist an explicit snapshot.
    if pool is None:
        return
    for kind in KINDS:
        target = policy.get(kind)
        if target is not None and target not in pool.get(kind, []):
            raise ValueError(f'项目默认 {kind} 模型必须先加入项目可用模型')


def require_model_in_pool(kind, model_id, pool):
    if kind == 'storyboard':
        kind = 'text'
    if pool is None:
        return
    if kind not in MODEL_POOL_KINDS or {'model_id': model_id} not in pool.get(kind, []):
        raise ValueError('所选平台模型不在本作品的可用模型范围内')


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
