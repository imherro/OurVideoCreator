"""Compile Film Bible shot bindings into immutable image-generation inputs."""
from __future__ import annotations

import json

from .visual_references import resolve_image_model_capabilities
from .generation_fingerprint import (
    PROMPT_COMPILER_VERSION,
    build_generation_fingerprint,
)
from .production_context import compose_project_document


GROUP_KINDS = {
    'character': {'character', 'character_state'},
    'scene': {'scene', 'scene_state'},
    'prop': {'prop'},
}


def _primary_reference(version):
    return next((
        item for item in version.get('references', [])
        if isinstance(item, dict) and item.get('role') == 'primary'
    ), None)


def _shot_for_image_node(document, node_id):
    return next((
        shot for shot in document.get('shots', [])
        if shot.get('imageNode') == node_id
        or (shot.get('pipeline') or {}).get('imageNodeId') == node_id
    ), None)


def _binding_rows(shot):
    bindings = shot.get('assetBindings') or {}
    rows = []
    for item in bindings.get('characters') or []:
        rows.append(('character', item))
    if bindings.get('scene'):
        rows.append(('scene', bindings['scene']))
    for item in bindings.get('props') or []:
        rows.append(('prop', item))
    return rows


def _version_chain(visual, bound_version):
    cards = visual.get('cards') or {}
    versions = visual.get('versions') or {}
    chain = []
    seen = set()
    current = bound_version
    while current:
        version_id = current.get('id')
        if not version_id or version_id in seen:
            raise ValueError('视觉版本 parentVersionId 存在循环，无法编译分镜提示词')
        seen.add(version_id)
        card = cards.get(current.get('cardId'))
        if not card:
            raise ValueError(f'视觉版本 {version_id} 所属卡片已丢失')
        chain.append((card, current))
        parent_id = current.get('parentVersionId')
        if not parent_id:
            break
        parent = versions.get(parent_id)
        if not parent:
            raise ValueError(f'视觉版本 {version_id} 的 parentVersionId 已悬空')
        parent_card = cards.get(parent.get('cardId'))
        if not parent_card:
            raise ValueError(f'父视觉版本 {parent_id} 所属卡片已丢失')
        if parent_card.get('id') not in (card.get('id'), card.get('parentCardId')):
            raise ValueError(f'视觉版本 {version_id} 的 parentVersionId 属于错误资产链')
        current = parent
    chain.reverse()
    bound_card = cards.get(bound_version.get('cardId')) or {}
    if bound_card.get('kind') in ('character_state', 'scene_state'):
        parent_card_id = bound_card.get('parentCardId')
        if not parent_card_id or not any(card.get('id') == parent_card_id for card, _ in chain[:-1]):
            raise ValueError(f'状态视觉版本 {bound_version.get("id")} 没有到基础资产的完整 parentVersionId 链')
    return chain


def _constraint_lines(index, group, chain):
    labels = {'character': '角色', 'scene': '场景', 'prop': '道具'}
    bound_card, _ = chain[-1]
    lines = [
        f"图{index}｜{labels[group]}｜{bound_card.get('name', bound_card['id'])}",
        '  版本链（根版本→当前绑定版本）：',
    ]
    for layer, (card, version) in enumerate(chain, 1):
        attributes = '；'.join(
            f"{str(item.get('name') or '').strip()}：{str(item.get('value') or '').strip()}"
            for item in version.get('spec', {}).get('attributes', [])
            if isinstance(item, dict) and item.get('name') and item.get('value')
        )
        invariants = '；'.join(
            str(item).strip() for item in version.get('invariants', []) if str(item).strip()
        )
        lines.append(
            f"    层{layer}｜{card.get('name', card['id'])}｜可见规格："
            f"{str(version.get('spec', {}).get('description') or '').strip() or '按参考图'}"
        )
        if attributes:
            lines.append(f"      固定属性：{attributes}")
        if invariants:
            lines.append(f"      不可改变：{invariants}")
    return lines


def _style_text(value):
    if value in (None, '', {}, []):
        return ''
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def compile_shot_prompt(document, shot, constraints):
    """Compile the final provider prompt only from canonical project state."""
    film_bible = document.get('filmBible') or {}
    project_style = _style_text(document.get('style'))
    bible_style = _style_text(film_bible.get('style'))
    lines = ['[项目视觉风格]']
    lines.append(f'项目风格：{project_style or "未指定"}')
    if bible_style:
        lines.append(f'视觉圣经风格：{bible_style}')
    lines.extend([
        '',
        '[本镜头变量]',
        f"首帧描述：{str(shot.get('image_prompt') or '').strip() or '按分镜结构生成首帧'}",
        f"动作：{str(shot.get('action') or '').strip() or '无额外动作说明'}",
        f"情绪：{str(shot.get('emotion') or '').strip() or '无额外情绪说明'}",
        f"摄影机：{str(shot.get('camera') or '').strip() or '无额外摄影机说明'}",
        '',
        '[视觉圣经一致性约束]',
        '以下图号对应按角色、场景、道具顺序提交的独立参考图；不要把它们理解为拼贴画。',
        *constraints,
        '必须保持上述身份、服装、场景结构和道具外观；只改变本镜头明确要求的动作、表情、构图和光线。',
    ])
    return '\n'.join(lines).strip()


def compile_shot_image_input(
    document, node_id, kind, input_value, providers, capability_resolver=None,
    production_context=None,
):
    """Return a provider-ready input compiled only from shot.assetBindings.

    Each reference remains an independent asset in semantic order. The compiler
    never creates a composite reference board and never truncates references.
    """
    result = dict(input_value)
    if kind != 'image':
        return result
    if production_context is not None:
        document = compose_project_document(document, production_context)
    shot = _shot_for_image_node(document, node_id)
    if not shot:
        return result
    rows = _binding_rows(shot)
    visual = ((document.get('filmBible') or {}).get('visual') or {})
    active_cards = [
        card for card in (visual.get('cards') or {}).values()
        if isinstance(card, dict) and not card.get('deletedAt') and card.get('status') != 'deprecated'
    ]
    if active_cards and not rows:
        raise ValueError('项目已有 Film Bible，所选分镜尚未绑定角色、场景或道具视觉版本')
    if not rows:
        return result
    result.pop('model_capabilities', None)
    result.pop('allow_reference_text_fallback', None)

    cards = visual.get('cards') or {}
    versions = visual.get('versions') or {}
    compiled = []
    constraint_lines = []
    for group, binding in rows:
        if not isinstance(binding, dict) or not binding.get('versionId'):
            raise ValueError('分镜视觉绑定缺少版本编号，请重新绑定资产')
        version_id = binding['versionId']
        version = versions.get(version_id)
        card = cards.get(version.get('cardId')) if isinstance(version, dict) else None
        if not version or not card:
            raise ValueError(f'分镜视觉绑定 {version_id} 已悬空，请重新绑定资产')
        if card.get('status') == 'deprecated':
            continue
        index = len(compiled) + 1
        if card.get('kind') not in GROUP_KINDS[group]:
            raise ValueError(f'分镜视觉绑定 {card.get("name", version_id)} 的资产类型不正确')
        confirmed_deprecated = (
            version.get('status') == 'deprecated'
            and (version.get('provenance') or {}).get('lockedAt') is not None
        )
        if version.get('status') != 'locked' and not confirmed_deprecated:
            raise ValueError(f'高一致性生成要求先确认并锁定“{card.get("name", version_id)}”的主参考图')
        reference = _primary_reference(version)
        asset_id = reference.get('assetId') if reference else None
        if not asset_id:
            raise ValueError(f'高一致性生成缺少“{card.get("name", version_id)}”的主参考图')
        chain = _version_chain(visual, version)
        compiled.append({
            'group': group,
            'role': binding.get('role', ''),
            'cardId': card['id'],
            'versionId': version_id,
            'assetId': asset_id,
            'versionChain': [item['id'] for _, item in chain],
        })
        constraint_lines.extend(_constraint_lines(index, group, chain))

    if active_cards and not compiled:
        raise ValueError('项目已有 Film Bible，但所选分镜没有可用的视觉绑定')
    if not compiled:
        return result

    model_id = str(result.get('model_id') or '')
    provider = next((item for item in providers if item.get('id') == model_id and item.get('kind') == 'image'), None)
    if not provider:
        raise ValueError('分镜图片平台模型不存在或已停用')
    capabilities = (capability_resolver or resolve_image_model_capabilities)(provider, model_id)
    if not isinstance(capabilities, dict) or capabilities.get('image_reference') is not True:
        raise ValueError('所选图片模型未明确支持参考图；高一致性模式不会自动降级为纯文生图')
    maximum = capabilities.get('max_references')
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1:
        raise ValueError('所选图片模型未明确报告最大参考图数量，无法安全提交高一致性任务')
    if len(compiled) > maximum:
        raise ValueError(
            f'当前分镜绑定了 {len(compiled)} 张主参考图，但所选模型最多支持 {maximum} 张；'
            '请调整绑定或模型，系统不会截断参考图'
        )

    asset_ids = [item['assetId'] for item in compiled]
    result.update({
        'model_id': model_id,
        'prompt': compile_shot_prompt(document, shot, constraint_lines),
        'asset_ids': asset_ids,
        'image_reference_sources': [
            {'type': 'asset', 'asset_id': asset_id} for asset_id in asset_ids
        ],
        'reference_compiler': {
            'version': PROMPT_COMPILER_VERSION,
            'source': 'shot.assetBindings',
            'shotUid': str(shot.get('uid') or shot.get('id') or ''),
            'consistency': 'high',
            'model_id': model_id,
            'maximumReferences': maximum,
            'bindings': compiled,
        },
        'generation_fingerprint': build_generation_fingerprint(
            document, shot, '', model_id, PROMPT_COMPILER_VERSION,
        ),
    })
    return result
