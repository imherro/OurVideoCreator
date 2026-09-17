import copy
from backend.film_bible.versioning import validate_film_bible_transition


def fixture():
    version = {
        'id': 'hero-v1', 'cardId': 'hero', 'version': 1,
        'parentVersionId': None, 'status': 'locked',
        'spec': {'description': '灰色风衣', 'attributes': []},
        'invariants': ['脸型不变'], 'references': [{'role': 'primary', 'assetId': 'ref'}],
        'createdAt': 1, 'provenance': {'lockedAt': 2},
    }
    return {
        'filmBible': {'visual': {
            'cards': {'hero': {'id': 'hero', 'kind': 'character', 'name': '林岚', 'parentCardId': None, 'currentVersionId': 'hero-v1', 'status': 'active'}},
            'versions': {'hero-v1': version},
        }},
        'shots': [{'uid': 'shot-A', 'assetBindings': {'characters': [{'role': '林岚', 'versionId': 'hero-v1'}], 'scene': None, 'props': []}}],
    }


def test_server_rejects_locked_mutation_and_referenced_hard_delete_but_allows_deprecation():
    old = fixture()
    mutated = copy.deepcopy(old); mutated['filmBible']['visual']['versions']['hero-v1']['spec']['description'] = '金色风衣'
    try:
        validate_film_bible_transition(old, mutated)
        assert False, 'locked mutation should fail'
    except ValueError as exc:
        assert '不可原地修改' in str(exc)
    deleted = copy.deepcopy(old); del deleted['filmBible']['visual']['versions']['hero-v1']
    try:
        validate_film_bible_transition(old, deleted)
        assert False, 'referenced deletion should fail'
    except ValueError as exc:
        assert '仍被分镜引用' in str(exc)
    deprecated = copy.deepcopy(old); deprecated['filmBible']['visual']['versions']['hero-v1']['status'] = 'deprecated'
    assert validate_film_bible_transition(old, deprecated) is deprecated
    assert deprecated['shots'][0]['assetBindings']['characters'][0]['versionId'] == 'hero-v1'


def test_restore_deprecated_version_uses_nearest_history_without_changing_references():
    import pytest
    from backend.film_bible.versioning import restore_visual_version

    original = fixture()
    deprecated = copy.deepcopy(original)
    deprecated['filmBible']['visual']['versions']['hero-v1']['status'] = 'deprecated'
    restored, status = restore_visual_version(deprecated, 'hero-v1', [deprecated, original])
    assert status == 'locked'
    assert restored == original
    with pytest.raises(ValueError, match='不可原地修改'):
        validate_film_bible_transition(deprecated, restored)
    with pytest.raises(ValueError, match='未找到'):
        restore_visual_version(deprecated, 'hero-v1', [])

    mismatched = copy.deepcopy(original)
    mismatched['filmBible']['visual']['versions']['hero-v1']['invariants'] = []
    with pytest.raises(ValueError, match='内容不一致'):
        restore_visual_version(deprecated, 'hero-v1', [mismatched, original])

    deleted_card = copy.deepcopy(deprecated)
    deleted_card['filmBible']['visual']['cards']['hero'].update(status='deprecated', deletedAt=3)
    with pytest.raises(ValueError, match='先恢复所属资产卡'):
        restore_visual_version(deleted_card, 'hero-v1', [original])


def test_restore_draft_does_not_lock_or_switch_current_version():
    from backend.film_bible.versioning import restore_visual_version

    original = fixture()
    original['filmBible']['visual']['versions']['hero-v1']['status'] = 'draft'
    deprecated = copy.deepcopy(original)
    deprecated['filmBible']['visual']['versions']['hero-v1']['status'] = 'deprecated'
    restored, status = restore_visual_version(deprecated, 'hero-v1', [original])
    assert status == 'draft'
    assert restored == original
