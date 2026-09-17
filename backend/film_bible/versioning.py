"""Server-side integrity rules for immutable Film Bible versions."""
from __future__ import annotations

import copy


def _visual(document):
    return ((document.get('filmBible') or {}).get('visual') or {})


def _bound_version_ids(document):
    result = set()
    for shot in document.get('shots') or []:
        bindings = shot.get('assetBindings') or {}
        for item in bindings.get('characters') or []:
            if isinstance(item, dict) and item.get('versionId'):
                result.add(item['versionId'])
        scene = bindings.get('scene')
        if isinstance(scene, dict) and scene.get('versionId'):
            result.add(scene['versionId'])
        for item in bindings.get('props') or []:
            if isinstance(item, dict) and item.get('versionId'):
                result.add(item['versionId'])
    return result


def _without_status(version):
    value = copy.deepcopy(version)
    value.pop('status', None)
    return value


def validate_film_bible_transition(previous, updated, *, restored_statuses=None):
    """Reject destructive saves while allowing explicit, auditable upgrades.

    The project document remains the persistence boundary. This validator does
    not create jobs, assets, or provider calls.
    """
    before = _visual(previous)
    after = _visual(updated)
    old_versions = before.get('versions') or {}
    new_versions = after.get('versions') or {}
    referenced = _bound_version_ids(previous) | _bound_version_ids(updated)

    for version_id, old in old_versions.items():
        new = new_versions.get(version_id)
        if new is None:
            if version_id in referenced:
                raise ValueError('仍被分镜引用的视觉版本不能永久删除；请改为弃用')
            if old.get('status') in ('locked', 'deprecated'):
                raise ValueError('已锁定或已弃用的视觉版本必须作为历史保留')
            continue
        if old.get('status') in ('locked', 'deprecated'):
            allowed_deprecation = (
                old.get('status') == 'locked'
                and new.get('status') == 'deprecated'
                and _without_status(old) == _without_status(new)
            )
            allowed_restore = (
                old.get('status') == 'deprecated'
                and new.get('status') in ('draft', 'pending_reference', 'locked')
                and (restored_statuses or {}).get(version_id) == new.get('status')
                and _without_status(old) == _without_status(new)
            )
            if new != old and not allowed_deprecation and not allowed_restore:
                raise ValueError('已锁定或已弃用的视觉版本不可原地修改')

    cards = after.get('cards') or {}
    for key, version in new_versions.items():
        if not isinstance(version, dict) or version.get('id') != key:
            raise ValueError('视觉版本编号与索引不一致')
        if version.get('cardId') not in cards:
            raise ValueError('视觉版本所属卡片不存在')
        number = version.get('version')
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise ValueError('视觉版本序号必须是正整数')
        parent_id = version.get('parentVersionId')
        if parent_id:
            parent = new_versions.get(parent_id)
            if not parent:
                raise ValueError('视觉版本 parentVersionId 已悬空')
            parent_card = cards.get(parent.get('cardId')) or {}
            card = cards[version['cardId']]
            if parent_card.get('id') not in (card.get('id'), card.get('parentCardId')):
                raise ValueError('视觉版本 parentVersionId 属于错误资产链')
            if parent_card.get('id') == card.get('id') and number <= parent.get('version', 0):
                raise ValueError('同一视觉卡的新版本序号必须递增')
    for card_id, card in cards.items():
        current = new_versions.get(card.get('currentVersionId'))
        if not current or current.get('cardId') != card_id:
            raise ValueError('视觉卡当前版本不存在或属于其他卡片')
        numbers = [item.get('version') for item in new_versions.values() if item.get('cardId') == card_id]
        if len(numbers) != len(set(numbers)):
            raise ValueError('同一视觉卡的版本序号不能重复')
    for version_id in _bound_version_ids(updated):
        if version_id not in new_versions:
            raise ValueError('分镜引用的视觉版本不存在')

    return updated


def restore_visual_version(context, version_id, history):
    """Restore only a status proven by newest-first immutable snapshots.

    ``history`` may be a lazy iterator.  The first snapshot containing a
    non-deprecated copy is authoritative: a content mismatch is an error, not
    permission to search farther back for a coincidentally matching version.
    """
    visual = _visual(context)
    version = (visual.get('versions') or {}).get(version_id)
    if not version or version.get('status') != 'deprecated':
        raise ValueError('该版本不存在或已不是弃用状态，请刷新后重试')
    card = (visual.get('cards') or {}).get(version.get('cardId')) or {}
    if card.get('deletedAt') or card.get('status') == 'deprecated':
        raise ValueError('请先恢复所属资产卡片')
    for snapshot in history:
        previous = (_visual(snapshot).get('versions') or {}).get(version_id)
        if not previous or previous.get('status') == 'deprecated':
            continue
        status = previous.get('status')
        if status not in ('draft', 'pending_reference', 'locked') or _without_status(previous) != _without_status(version):
            raise ValueError('历史版本内容不一致，无法安全恢复')
        updated = copy.deepcopy(context)
        updated['filmBible']['visual']['versions'][version_id]['status'] = status
        validate_film_bible_transition(context, updated, restored_statuses={version_id: status})
        return updated, status
    raise ValueError('未找到弃用前的历史状态，无法自动恢复')
