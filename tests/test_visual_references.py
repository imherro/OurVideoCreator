import pytest

from backend.visual_references import validate_visual_reference_job


PROVIDERS = [{
    'id': 'seedream', 'kind': 'image', 'capabilities': {'image_reference': True},
}]


def document():
    return {
        'generationPolicy': {'text': None, 'image': {'model_id': 'seedream'}, 'video': None},
        'filmBible': {'visual': {'cards': {
            'hero': {'id': 'hero', 'kind': 'character', 'status': 'active'},
            'wet': {'id': 'wet', 'kind': 'character_state', 'status': 'active'},
        }, 'versions': {
            'hero-v1': {
                'id': 'hero-v1', 'cardId': 'hero', 'status': 'locked',
                'parentVersionId': None,
                'references': [{'role': 'primary', 'assetId': 'asset-parent'}],
            },
            'wet-v1': {
                'id': 'wet-v1', 'cardId': 'wet', 'status': 'draft',
                'parentVersionId': 'hero-v1', 'references': [],
            },
        }}},
    }


def state_input():
    return {
        'model_id': 'seedream', 'prompt': '雨中状态',
        'asset_ids': ['asset-parent'], 'asset_category': 'character',
        'visual_reference': {
            'versionId': 'wet-v1', 'targetSource': 'project',
            'parentVersionId': 'hero-v1',
            'parentReferenceAssetId': 'asset-parent',
        },
    }


def test_state_reference_job_must_use_policy_and_frozen_locked_parent():
    doc = document()
    supports_reference = lambda provider, model_id: {'image_reference': True}
    validate_visual_reference_job(doc, 'visual-version:wet-v1', 'image', state_input(), PROVIDERS, supports_reference)
    wrong = state_input(); wrong['asset_ids'] = []
    with pytest.raises(ValueError, match='必须且只能发送'):
        validate_visual_reference_job(doc, 'visual-version:wet-v1', 'image', wrong, PROVIDERS, supports_reference)
    wrong = state_input(); wrong['model_id'] = 'another-model'
    with pytest.raises(ValueError, match='生成策略不一致'):
        validate_visual_reference_job(doc, 'visual-version:wet-v1', 'image', wrong, PROVIDERS, supports_reference)
    doc['filmBible']['visual']['versions']['hero-v1']['status'] = 'pending_reference'
    with pytest.raises(ValueError, match='先确认并锁定父版本'):
        validate_visual_reference_job(doc, 'visual-version:wet-v1', 'image', state_input(), PROVIDERS, supports_reference)


@pytest.mark.parametrize('capabilities', [None, {}, {'image_reference': False}])
def test_state_reference_job_requires_server_confirmed_image_reference(capabilities):
    with pytest.raises(ValueError, match='未明确支持参考图'):
        validate_visual_reference_job(
            document(), 'visual-version:wet-v1', 'image', state_input(), PROVIDERS,
            lambda provider, model_id: capabilities,
        )


def test_state_reference_job_rejects_model_missing_from_server_catalog():
    def missing(provider, model_id):
        raise ValueError('图片模型目录中找不到所选模型')
    with pytest.raises(ValueError, match='目录中找不到'):
        validate_visual_reference_job(
            document(), 'visual-version:wet-v1', 'image', state_input(), PROVIDERS, missing,
        )


def test_base_reference_job_rejects_hidden_image_conditioning():
    doc = document()
    value = {
        'model_id': 'seedream', 'prompt': '角色定妆',
        'asset_ids': [], 'asset_category': 'character',
        'visual_reference': {'versionId': 'hero-v1', 'targetSource': 'project'},
    }
    doc['filmBible']['visual']['versions']['hero-v1']['status'] = 'draft'
    validate_visual_reference_job(
        doc, 'visual-version:hero-v1', 'image', value, PROVIDERS,
        lambda provider, model_id: (_ for _ in ()).throw(AssertionError('base card must not resolve capabilities')),
    )
    value['asset_ids'] = ['unrecorded-reference']
    with pytest.raises(ValueError, match='必须从文字规格生成'):
        validate_visual_reference_job(doc, 'visual-version:hero-v1', 'image', value, PROVIDERS)
