import pytest

from backend.reference_compiler import compile_shot_image_input


PROVIDERS = [{
    'id': 'image-model', 'name': 'Image Provider', 'type': 'openai',
    'kind': 'image', 'local': True, 'model': 'image-model',
}]


def document():
    cards = {
        'hero': {'id': 'hero', 'kind': 'character', 'name': '林岚'},
        'friend': {'id': 'friend', 'kind': 'character', 'name': '阿杰'},
        'alley': {'id': 'alley', 'kind': 'scene', 'name': '雨巷'},
        'umbrella': {'id': 'umbrella', 'kind': 'prop', 'name': '红伞'},
    }
    versions = {}
    for card_id, card in cards.items():
        version_id = card_id + '-v1'
        versions[version_id] = {
            'id': version_id, 'cardId': card_id, 'status': 'locked',
            'spec': {
                'description': card['name'] + '的固定外观',
                'attributes': [{'name': '颜色', 'value': card_id + '-color'}],
            },
            'invariants': [card['name'] + '不可改变'],
            'references': [{'role': 'primary', 'assetId': 'asset-' + card_id}],
            'provenance': {'lockedAt': 1},
        }
    return {
        'style': '电影写实，冷色雨夜',
        'filmBible': {
            'visual': {'cards': cards, 'versions': versions},
            'style': {'palette': '冷蓝', 'lighting': '路灯侧逆光'},
        },
        'shots': [{
            'id': 'shot-001', 'uid': 'shot-stable', 'imageNode': 'image-1',
            'image_prompt': '林岚在雨巷中的动作前首帧',
            'action': '林岚撑伞向前走', 'emotion': '警觉', 'camera': '中景缓慢推进',
            'assetBindings': {
                'characters': [
                    {'role': '主角', 'versionId': 'hero-v1'},
                    {'role': '朋友', 'versionId': 'friend-v1'},
                ],
                'scene': {'versionId': 'alley-v1'},
                'props': [{'role': '关键道具', 'versionId': 'umbrella-v1'}],
            },
        }],
        'nodes': [
            {'id': 'visual', 'data': {'managed': True, 'kind': 'visual_asset'}},
            {'id': 'manual-reference', 'data': {'kind': 'reference', 'assetId': 'asset-manual'}},
            {'id': 'image-1', 'data': {'kind': 'image'}},
        ],
        'edges': [
            {'source': 'visual', 'target': 'image-1'},
            {'source': 'manual-reference', 'target': 'image-1'},
        ],
    }


def input_value():
    return {
        'model_id': 'image-model',
        'prompt': '把林岚改成金发并换成红衣服',
        'asset_ids': ['asset-manual'],
    }


def test_compiler_accepts_separate_production_context():
    value = document()
    expected = compile_shot_image_input(
        value, 'image-1', 'image', input_value(), PROVIDERS,
        lambda provider, model: {'image_reference': True, 'max_references': 8},
    )
    context = {
        'schemaVersion': 1,
        'style': value['style'],
        'filmBible': value['filmBible'],
        'generationPolicy': {'text': None, 'image': None, 'video': None},
    }
    episode = {key: item for key, item in value.items() if key not in ('style', 'filmBible', 'generationPolicy')}
    actual = compile_shot_image_input(
        episode, 'image-1', 'image', input_value(), PROVIDERS,
        lambda provider, model: {'image_reference': True, 'max_references': 8},
        production_context=context,
    )
    assert actual == expected


def supports(maximum=4):
    return lambda provider, model_id: {
        'image_reference': True, 'max_references': maximum,
    }


def test_compiler_uses_only_asset_bindings_in_character_scene_prop_order():
    value = {
        **input_value(),
        'model_capabilities': {'image_reference': False, 'max_references': 1},
        'allow_reference_text_fallback': True,
    }
    result = compile_shot_image_input(
        document(), 'image-1', 'image', value, PROVIDERS, supports(),
    )
    assert result['asset_ids'] == [
        'asset-hero', 'asset-friend', 'asset-alley', 'asset-umbrella',
    ]
    assert result['image_reference_sources'] == [
        {'type': 'asset', 'asset_id': asset_id} for asset_id in result['asset_ids']
    ]
    assert [item['group'] for item in result['reference_compiler']['bindings']] == [
        'character', 'character', 'scene', 'prop',
    ]
    assert result['reference_compiler']['source'] == 'shot.assetBindings'
    assert 'asset-manual' not in result['asset_ids']
    assert 'model_capabilities' not in result
    assert 'allow_reference_text_fallback' not in result
    assert '视觉圣经一致性约束' in result['prompt']
    assert '把林岚改成金发' not in result['prompt']
    assert '项目风格：电影写实，冷色雨夜' in result['prompt']
    assert '视觉圣经风格：{"lighting":"路灯侧逆光","palette":"冷蓝"}' in result['prompt']
    assert '首帧描述：林岚在雨巷中的动作前首帧' in result['prompt']
    assert '动作：林岚撑伞向前走' in result['prompt']
    assert '情绪：警觉' in result['prompt']
    assert '摄影机：中景缓慢推进' in result['prompt']
    assert '可见规格：林岚的固定外观' in result['prompt']
    assert '固定属性：颜色：hero-color' in result['prompt']
    assert '不可改变：林岚不可改变' in result['prompt']
    assert '拼贴画' in result['prompt']
    assert 'composite' not in result['reference_compiler']
    assert result['generation_fingerprint']['algorithm'] == 'sha256'
    assert 'providerId' not in result['generation_fingerprint']['inputs']
    assert result['generation_fingerprint']['inputs']['model_id'] == 'image-model'
    assert [item['versionId'] for item in result['generation_fingerprint']['inputs']['boundVisualVersions']] == [
        'hero-v1', 'friend-v1', 'alley-v1', 'umbrella-v1',
    ]


def state_document():
    value = document()
    visual = value['filmBible']['visual']
    visual['cards']['wet'] = {
        'id': 'wet', 'kind': 'character_state', 'name': '雨中的林岚',
        'parentCardId': 'hero',
    }
    visual['versions']['wet-v1'] = {
        'id': 'wet-v1', 'cardId': 'wet', 'parentVersionId': 'hero-v1',
        'status': 'locked',
        'spec': {
            'description': '黑色短发被雨淋湿，灰色风衣湿透',
            'attributes': [{'name': '湿润状态', 'value': '持续滴水'}],
        },
        'invariants': ['仍是林岚', '灰色风衣款式不变'],
        'references': [{'role': 'primary', 'assetId': 'asset-wet'}],
        'provenance': {'lockedAt': 2},
    }
    value['shots'][0]['assetBindings'] = {
        'characters': [{'role': '主角', 'versionId': 'wet-v1'}],
        'scene': None, 'props': [],
    }
    return value


def test_state_binding_compiles_root_to_bound_version_chain_and_canonical_shot():
    result = compile_shot_image_input(
        state_document(), 'image-1', 'image', input_value(), PROVIDERS, supports(),
    )
    assert result['asset_ids'] == ['asset-wet']
    assert result['reference_compiler']['bindings'][0]['versionChain'] == ['hero-v1', 'wet-v1']
    prompt = result['prompt']
    assert prompt.index('林岚的固定外观') < prompt.index('黑色短发被雨淋湿')
    assert '林岚不可改变' in prompt
    assert '仍是林岚' in prompt
    assert '项目风格：电影写实，冷色雨夜' in prompt
    assert '动作：林岚撑伞向前走' in prompt
    assert '情绪：警觉' in prompt
    assert '摄影机：中景缓慢推进' in prompt
    assert '把林岚改成金发' not in prompt


@pytest.mark.parametrize('mutation,match', [
    ('dangling', 'parentVersionId 已悬空'),
    ('cycle', '存在循环'),
    ('wrong_card', '属于错误资产链'),
])
def test_state_version_chain_rejects_dangling_cycle_and_wrong_card(mutation, match):
    value = state_document()
    version = value['filmBible']['visual']['versions']['wet-v1']
    if mutation == 'dangling':
        version['parentVersionId'] = 'missing-version'
    elif mutation == 'cycle':
        version['parentVersionId'] = 'wet-v1'
    else:
        version['parentVersionId'] = 'friend-v1'
    with pytest.raises(ValueError, match=match):
        compile_shot_image_input(
            value, 'image-1', 'image', input_value(), PROVIDERS, supports(),
        )


@pytest.mark.parametrize('capabilities', [
    None,
    {},
    {'image_reference': False, 'max_references': 4},
    {'image_reference': True},
    {'image_reference': True, 'max_references': None},
])
def test_compiler_requires_explicit_reference_support_and_limit(capabilities):
    value = {**input_value(), 'allow_reference_text_fallback': True}
    with pytest.raises(ValueError, match='未明确支持参考图|最大参考图数量'):
        compile_shot_image_input(
            document(), 'image-1', 'image', value, PROVIDERS,
            lambda provider, model_id: capabilities,
        )


def test_compiler_blocks_missing_model_and_never_truncates_excess_references():
    with pytest.raises(ValueError, match='目录中找不到'):
        compile_shot_image_input(
            document(), 'image-1', 'image', input_value(), PROVIDERS,
            lambda provider, model_id: (_ for _ in ()).throw(ValueError('模型目录中找不到该模型')),
        )
    with pytest.raises(ValueError, match='绑定了 4 张.*最多支持 3 张.*不会截断'):
        compile_shot_image_input(
            document(), 'image-1', 'image', input_value(), PROVIDERS, supports(3),
        )


def test_high_consistency_blocks_unlocked_or_missing_primary_references():
    unlocked = document()
    unlocked['filmBible']['visual']['versions']['hero-v1']['status'] = 'pending_reference'
    with pytest.raises(ValueError, match='确认并锁定'):
        compile_shot_image_input(
            unlocked, 'image-1', 'image', input_value(), PROVIDERS, supports(),
        )
    missing = document()
    missing['filmBible']['visual']['versions']['hero-v1']['references'] = []
    with pytest.raises(ValueError, match='缺少.*主参考图'):
        compile_shot_image_input(
            missing, 'image-1', 'image', input_value(), PROVIDERS, supports(),
        )


def test_non_shot_is_untouched_and_film_bible_unbound_shot_is_rejected():
    value = input_value()
    assert compile_shot_image_input(
        document(), 'other-image', 'image', value, PROVIDERS,
        lambda *_: (_ for _ in ()).throw(AssertionError('must not resolve')),
    ) == value
    unbound = document()
    unbound['shots'][0]['assetBindings'] = {'characters': [], 'scene': None, 'props': []}
    with pytest.raises(ValueError, match='尚未绑定'):
        compile_shot_image_input(
            unbound, 'image-1', 'image', value, PROVIDERS,
            lambda *_: (_ for _ in ()).throw(AssertionError('must not resolve')),
        )


def test_deprecated_previously_locked_version_remains_resolvable_for_old_shot():
    value = document()
    version = value['filmBible']['visual']['versions']['hero-v1']
    version['status'] = 'deprecated'
    version.setdefault('provenance', {})['lockedAt'] = 123
    result = compile_shot_image_input(
        value, 'image-1', 'image', input_value(), PROVIDERS, supports(),
    )
    assert result['reference_compiler']['bindings'][0]['versionId'] == 'hero-v1'
    assert result['asset_ids'][0] == 'asset-hero'


def test_soft_deleted_card_is_ignored_until_restored():
    value = document()
    value['filmBible']['visual']['cards']['hero']['status'] = 'deprecated'
    value['filmBible']['visual']['cards']['hero']['deletedAt'] = 123
    result = compile_shot_image_input(
        value, 'image-1', 'image', input_value(), PROVIDERS, supports(),
    )
    assert 'asset-hero' not in result['asset_ids']
    assert all(
        item['cardId'] != 'hero'
        for item in result['reference_compiler']['bindings']
    )
