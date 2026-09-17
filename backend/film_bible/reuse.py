"""Reuse production visual identities without rewriting shared history."""
from __future__ import annotations

import copy
import json
import unicodedata


def name_key(name):
    return ''.join(unicodedata.normalize('NFKC', str(name)).casefold().split())


def available_cards(visual):
    versions = visual.get('versions') or {}
    cards = {
        card_id: card for card_id, card in (visual.get('cards') or {}).items()
        if not card.get('deletedAt') and card.get('status') != 'deprecated'
        and versions.get(card.get('currentVersionId'), {}).get('status') not in (None, 'deprecated')
    }
    return {
        card_id: card for card_id, card in cards.items()
        if not card.get('parentCardId') or card['parentCardId'] in cards
    }


def visual_catalog(visual):
    result = []
    for card_id, card in available_cards(visual).items():
        version = visual['versions'][card['currentVersionId']]
        result.append({
            'key': card_id,
            'kind': card['kind'],
            'name': card['name'],
            'parent_key': card.get('parentCardId') or '',
            'description': version.get('spec', {}).get('description', ''),
            'attributes': version.get('spec', {}).get('attributes', []),
            'invariants': version.get('invariants', []),
            'aliases': card.get('aliases') or [],
            'versionId': version['id'],
            'status': version['status'],
            'hasReference': bool(version.get('references')),
        })
    return result


def visual_user_prompt(script, existing):
    if existing is None:
        return script
    return script + '\n\n[整部作品已有视觉资产，可跨集复用]\n' + json.dumps(
        visual_catalog(existing), ensure_ascii=False,
    ) + '''
先识别本集实际需要的已有角色、场景、道具和状态。同一身份必须复用其 key，保留已有外观与 invariants；不得仅因换集而重建卡片。简称、别名、称谓改变不代表新人物；同一角色的化形、性别外观或年龄变化应建立关联状态，不重建基础身份。
输出 cards 只含本集需要的实体及状态的基础父卡；复用项沿用给定 key 和 parent_key，仍按 Schema 填写描述。已有资产的描述和已确认参考图由系统保留，不会被生成文本覆盖。
确实新增的实体使用新的语义 key。已有角色换装、持续伤势或场景昼夜变化等，使用新的状态卡，并以已有基础卡 key 作为 parent_key；动作或临时情绪不是新资产。
后续镜头和对白必须使用这些 key。不要根据已有资产清单给本集增加剧本中没有的人物或剧情。'''


def normalize_reusable_visual(value, existing, provider_id='', model_id=''):
    """Normalize model output and reuse current canonical cards by identity."""
    from .validate import normalize_visual_bible
    if existing is None:
        return normalize_visual_bible(value, provider_id, model_id)
    # A newly generated state may point to an existing parent omitted from the
    # model output. Add a schema-shaped parent solely for normalization.
    value = copy.deepcopy(value)
    catalog = {item['key']: item for item in visual_catalog(existing)}
    if isinstance(value, dict) and isinstance(value.get('cards'), list):
        keys = {item.get('key') for item in value['cards'] if isinstance(item, dict)}
        for item in list(value['cards']):
            parent = item.get('parent_key') if isinstance(item, dict) else None
            if parent in catalog and parent not in keys:
                value['cards'].append({
                    key: child for key, child in catalog[parent].items()
                    if key not in ('versionId', 'status', 'hasReference', 'aliases')
                })
                keys.add(parent)
    fresh, keys = normalize_visual_bible(value, provider_id, model_id)
    merged = copy.deepcopy(existing)
    merged.setdefault('cards', {})
    merged.setdefault('versions', {})
    available = available_cards(existing)
    resolved = {}
    # Resolve parents first because parent identity is part of state matching.
    ordered = sorted(keys.items(), key=lambda item: bool(fresh['cards'][item[1][0]].get('parentCardId')))
    for key, (card_id, version_id) in ordered:
        card, version = fresh['cards'][card_id], fresh['versions'][version_id]
        parent = card.get('parentCardId')
        parent_pair = resolved.get(parent)
        if key in (existing.get('cards') or {}):
            candidate = available.get(key)
            if (not candidate or candidate['kind'] != card['kind'] or
                    (candidate.get('parentCardId') or None) != (parent_pair[0] if parent_pair else None)):
                raise ValueError(f'已有视觉卡 {key} 不可复用或父级/类型不匹配')
        else:
            matches = [
                old for old in available.values()
                if old['kind'] == card['kind']
                and name_key(card['name']) in {
                    name_key(name) for name in [old['name'], *(old.get('aliases') or [])]
                }
                and (old.get('parentCardId') or None) == (parent_pair[0] if parent_pair else None)
            ]
            if len(matches) > 1:
                raise ValueError(f'视觉资产 {card["name"]} 存在多个同名候选，请明确沿用清单中的 key')
            candidate = matches[0] if matches else None
        if candidate:
            pair = (candidate['id'], candidate['currentVersionId'])
        else:
            if parent_pair:
                card['parentCardId'] = parent_pair[0]
                version['parentVersionId'] = parent_pair[1]
            merged['cards'][card_id] = card
            merged['versions'][version_id] = version
            pair = (card_id, version_id)
        resolved[card_id] = pair
        keys[key] = pair
    return merged, keys


def merge_candidate_visual(existing, candidate_visual, shots):
    """Prepare a storyboard candidate for collaborative adoption.

    Existing objects are never returned as writes. Legacy candidates with new
    IDs are conservatively remapped by exact normalized name/alias, kind and
    canonical parent. Ambiguous matches fail instead of duplicating identity.
    """
    if not candidate_visual:
        return {'cards': {}, 'versions': {}}, copy.deepcopy(shots)
    if not isinstance(candidate_visual, dict):
        raise ValueError('候选视觉资料无效')
    incoming_cards = candidate_visual.get('cards') or {}
    incoming_versions = candidate_visual.get('versions') or {}
    if not isinstance(incoming_cards, dict) or not isinstance(incoming_versions, dict):
        raise ValueError('候选视觉卡或版本无效')
    old_cards = existing.get('cards') or {}
    old_versions = existing.get('versions') or {}
    available = available_cards(existing)
    card_map = {}
    version_map = {}
    new_cards = {}
    new_versions = {}
    resolving_cards = set()
    resolving_versions = set()

    def resolve_card(card_id, *, as_parent=False):
        if card_id in card_map:
            resolved = card_map[card_id]
            if as_parent and resolved in old_cards and resolved not in available:
                raise ValueError('新视觉状态不能引用已弃用或不可用的父卡')
            return resolved
        card = incoming_cards.get(card_id)
        if card_id in old_cards:
            if card is not None and (card.get('kind') != old_cards[card_id].get('kind') or
                    (card.get('parentCardId') or None) != (old_cards[card_id].get('parentCardId') or None)):
                raise ValueError(f'候选视觉卡 {card_id} 与现有类型或父级不一致')
            card_map[card_id] = card_id
            if as_parent and card_id not in available:
                raise ValueError('新视觉状态不能引用已弃用或不可用的父卡')
            return card_id
        if not isinstance(card, dict) or card.get('id') != card_id:
            raise ValueError(f'候选视觉卡 {card_id} 不存在或编号不一致')
        if card_id in resolving_cards:
            raise ValueError('候选视觉卡父级形成循环')
        resolving_cards.add(card_id)
        parent_id = card.get('parentCardId')
        parent = resolve_card(parent_id, as_parent=True) if parent_id else None
        matches = [
            old for old in available.values()
            if old.get('kind') == card.get('kind')
            and name_key(card.get('name')) in {
                name_key(name) for name in [old.get('name'), *(old.get('aliases') or [])]
            }
            and (old.get('parentCardId') or None) == parent
        ]
        if len(matches) > 1:
            raise ValueError(f'视觉资产 {card.get("name") or card_id} 存在多个同名候选，请重新生成并明确复用 key')
        if matches:
            resolved = matches[0]['id']
        else:
            resolved = card_id
            new_cards[card_id] = {**copy.deepcopy(card), 'parentCardId': parent}
        card_map[card_id] = resolved
        resolving_cards.remove(card_id)
        return resolved

    def resolve_version(version_id):
        if version_id in version_map:
            return version_map[version_id]
        if version_id in old_versions:
            version = incoming_versions.get(version_id)
            if version is not None:
                mapped_card = resolve_card(version.get('cardId'))
                if old_versions[version_id].get('cardId') != mapped_card:
                    raise ValueError(f'候选视觉版本 {version_id} 所属卡片不一致')
            version_map[version_id] = version_id
            return version_id
        version = incoming_versions.get(version_id)
        if not isinstance(version, dict) or version.get('id') != version_id:
            raise ValueError(f'候选视觉版本 {version_id} 不存在或编号不一致')
        if version_id in resolving_versions:
            raise ValueError('候选视觉版本父级形成循环')
        resolving_versions.add(version_id)
        source_card = version.get('cardId')
        mapped_card = resolve_card(source_card)
        if mapped_card != source_card:
            current = old_cards[mapped_card].get('currentVersionId')
            if current not in old_versions:
                raise ValueError('复用视觉卡缺少当前版本')
            resolved = current
        elif mapped_card in old_cards:
            raise ValueError('分镜候选不能向已有视觉卡追加版本；请从视觉资产页显式派生')
        else:
            parent_version = version.get('parentVersionId')
            resolved_parent = resolve_version(parent_version) if parent_version else None
            resolved = version_id
            new_versions[version_id] = {
                **copy.deepcopy(version), 'cardId': mapped_card, 'parentVersionId': resolved_parent,
            }
        version_map[version_id] = resolved
        resolving_versions.remove(version_id)
        return resolved

    for card_id in incoming_cards:
        resolve_card(card_id)
    for version_id in incoming_versions:
        resolve_version(version_id)
    for card_id, card in list(new_cards.items()):
        current = resolve_version(card.get('currentVersionId'))
        if current not in new_versions or new_versions[current].get('cardId') != card_id:
            raise ValueError('新增视觉卡当前版本不存在或被错误复用')
        card['currentVersionId'] = current

    def remap_binding(item, allowed_kinds):
        if not isinstance(item, dict) or not isinstance(item.get('versionId'), str):
            raise ValueError('候选分镜视觉绑定无效')
        version_id = resolve_version(item['versionId'])
        version = old_versions.get(version_id) or new_versions.get(version_id)
        card = (old_cards.get(version.get('cardId')) or new_cards.get(version.get('cardId'))) if version else None
        if not version or not card or card.get('kind') not in allowed_kinds:
            raise ValueError('候选分镜视觉绑定类型或版本无效')
        if version.get('status') == 'deprecated' or card.get('status') == 'deprecated' or card.get('deletedAt'):
            raise ValueError('候选分镜不能绑定已弃用的视觉版本')
        return {**copy.deepcopy(item), 'versionId': version_id,
                **({'role': card['name']} if item.get('role') else {})}

    remapped = []
    for raw in shots:
        shot = copy.deepcopy(raw)
        binding = shot.get('assetBindings')
        if binding is not None:
            if not isinstance(binding, dict):
                raise ValueError('候选分镜视觉绑定无效')
            shot['assetBindings'] = {
                **binding,
                'characters': [remap_binding(item, {'character', 'character_state'})
                               for item in binding.get('characters') or []],
                'scene': remap_binding(binding['scene'], {'scene', 'scene_state'})
                         if binding.get('scene') else None,
                'props': [remap_binding(item, {'prop'}) for item in binding.get('props') or []],
            }
        dialogues = []
        for line in shot.get('dialogues') or []:
            if not isinstance(line, dict) or not isinstance(line.get('characterCardId'), str):
                raise ValueError('候选分镜对白角色无效')
            card_id = resolve_card(line['characterCardId'])
            card = old_cards.get(card_id) or new_cards.get(card_id)
            if not card or card.get('kind') != 'character':
                raise ValueError('候选分镜对白必须绑定基础角色卡')
            dialogues.append({**line, 'characterCardId': card_id, 'characterName': card['name']})
        shot['dialogues'] = dialogues
        remapped.append(shot)
    return {'cards': new_cards, 'versions': new_versions}, remapped
