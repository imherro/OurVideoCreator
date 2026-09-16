"""Provider-neutral generation target selection."""
from __future__ import annotations

KINDS = ('text', 'image', 'video')

def default_ark_policy(providers):
    ark = next((p for p in providers if p.get('type') == 'volcengine_ark'), None)
    if not ark:
        return {kind: None for kind in KINDS}
    models = ark.get('models') or {}
    return {kind: {'providerId': ark['id'], 'modelId': models.get(kind, '')} for kind in KINDS}

def validate_generation_policy(policy, providers, allow_missing=False):
    if not isinstance(policy, dict):
        raise ValueError('项目生成策略必须是对象')
    configured = {p.get('id'): p for p in providers}
    result = {}
    for kind in KINDS:
        target = policy.get(kind)
        if target is None:
            result[kind] = None
            continue
        if not isinstance(target, dict) or not target.get('providerId'):
            raise ValueError(f'项目默认{kind}模型配置无效')
        if target['providerId'] == 'local':
            raise ValueError(f'项目默认{kind}模型仍指向已移除的本地推理，请选择外部 Provider')
        provider = configured.get(target['providerId'])
        if not provider and allow_missing:
            result[kind] = {'providerId': target['providerId'], 'modelId': str(target.get('modelId', ''))}
            continue
        if not provider:
            raise ValueError(f'项目默认{kind}模型所用服务已不存在，请重新选择')
        provider_kind = provider.get('kind')
        if provider_kind and provider_kind != kind:
            raise ValueError(f'项目默认{kind}模型与服务用途不匹配')
        result[kind] = {'providerId': target['providerId'], 'modelId': str(target.get('modelId', ''))}
    return result

def resolve_generation_target(kind, override, project_policy, providers, local_models=None):
    if kind not in KINDS:
        raise ValueError('不支持的生成类型')
    configured = {p.get('id'): p for p in providers}
    candidate = None
    source = 'system'
    if isinstance(override, dict) and override.get('mode') == 'override':
        candidate = {'providerId': override.get('providerId'), 'modelId': override.get('modelId', '')}
        source = 'override'
    elif isinstance(project_policy, dict) and project_policy.get(kind) is not None:
        candidate = project_policy[kind]
        source = 'project'
    if candidate:
        provider_id = candidate.get('providerId')
        if provider_id == 'local':
            raise ValueError(f'{source} 配置仍指向已移除的本地推理，请选择外部 Provider')
        provider = configured.get(provider_id)
        if not provider:
            raise ValueError(f'{source} 配置的模型服务已不存在，请重新选择；未自动切换其他服务')
        if provider.get('kind') and provider['kind'] != kind:
            raise ValueError(f'{source} 配置的模型服务不支持 {kind}')
        model = candidate.get('modelId') or (provider.get('models') or {}).get(kind) or provider.get('model', '')
        return {'providerId': provider_id, 'modelId': model, 'source': source}
    raise ValueError(f'尚未为项目配置默认 {kind} Provider；系统不会自动选择其他付费模型')
