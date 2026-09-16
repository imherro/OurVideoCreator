import copy

from backend.generation_fingerprint import build_generation_fingerprint
from backend.generation_staleness import reconcile_generation_staleness


def fixture():
    shot = {
        'id': 'A', 'uid': 'shot-A', 'imageNode': 'image-A', 'videoNode': 'video-A',
        'scene': '雨巷', 'characters': '林岚', 'action': '前行', 'emotion': '警觉',
        'camera': '中景', 'audio': '雨声', 'image_prompt': '首帧',
        'video_prompt': '前行后停下', 'duration': 5,
        'assetBindings': {'characters': [{'role': '林岚', 'versionId': 'hero-v1'}], 'scene': None, 'props': []},
    }
    document = {
        'filmBible': {'styleVersion': 1}, 'shots': [shot],
        'nodes': [
            {'id': 'image-A', 'data': {'kind': 'image', 'model_id': 'seedream', 'assetId': 'frame-A', 'resultJob': 'image-job'}},
            {'id': 'video-A', 'data': {'kind': 'video', 'assetId': 'clip-A', 'resultJob': 'video-job', 'generationFingerprint': {'hash': 'video-history'}}},
        ],
        'edges': [{'source': 'image-A', 'target': 'video-A'}],
    }
    document['nodes'][0]['data']['generationFingerprint'] = build_generation_fingerprint(
        document, shot, 'ark', 'seedream', 1,
    )
    return document


def test_reconciliation_marks_matching_fingerprint_current_without_jobs():
    document = fixture(); document['jobs'] = []
    result = reconcile_generation_staleness(document, prompt_compiler_version=1)
    image = result['nodes'][0]['data']
    assert image['generationStatus'] == 'current'
    assert image.get('stale') is not True
    assert result['jobs'] == [] and document['jobs'] == []


def test_reconciliation_clears_legacy_prompt_comparison_stale_flag():
    document = fixture()
    document['nodes'][0]['data']['stale'] = True
    result = reconcile_generation_staleness(document, prompt_compiler_version=1)
    image = result['nodes'][0]['data']
    assert image['generationStatus'] == 'current'
    assert image['stale'] is False


def test_reopen_reconciliation_detects_compiler_change_and_preserves_downstream_media():
    document = fixture(); document['jobs'] = []
    result = reconcile_generation_staleness(document, prompt_compiler_version=2)
    image, video = [node['data'] for node in result['nodes']]
    assert image['generationStatus'] == 'stale' and image['stale'] is True
    assert image['currentGenerationFingerprint']['hash'] != image['generationFingerprint']['hash']
    assert video['stale'] is True and video['staleReason'] == 'upstream-generation-stale'
    assert (image['assetId'], image['resultJob']) == ('frame-A', 'image-job')
    assert (video['assetId'], video['resultJob'], video['generationFingerprint']) == (
        'clip-A', 'video-job', {'hash': 'video-history'},
    )
    assert result['jobs'] == []


def test_reconciliation_detects_current_provider_or_model_change():
    for field, value in [('model_id', 'other-platform-model')]:
        document = fixture()
        document['nodes'][0]['data'][field] = value
        result = reconcile_generation_staleness(document, prompt_compiler_version=1)
        assert result['nodes'][0]['data']['generationStatus'] == 'stale'
        assert result['nodes'][1]['data']['stale'] is True
        assert document['nodes'][0]['data'].get('stale') is None
