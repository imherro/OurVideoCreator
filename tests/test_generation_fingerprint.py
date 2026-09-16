import copy

from backend.generation_fingerprint import (
    build_generation_fingerprint,
    fingerprint_status,
)


def fixture():
    return ({
        'style': '电影写实',
        'filmBible': {'style': {'palette': 'cold'}, 'styleVersion': 7},
    }, {
        'uid': 'shot-A', 'scene': '雨巷', 'characters': '林岚',
        'action': '向前走', 'emotion': '警觉', 'camera': '中景推进',
        'audio': '雨声', 'image_prompt': '动作前首帧',
        'video_prompt': '随后转身', 'duration': 5,
        'assetBindings': {
            'characters': [{'role': '林岚', 'versionId': 'hero-v1'}],
            'scene': {'versionId': 'alley-v1'}, 'props': [],
        },
    })


def test_fingerprint_is_deterministic_and_excludes_runtime_noise():
    document, shot = fixture()
    first = build_generation_fingerprint(document, shot, 'ark', 'seedream', 1)
    second = build_generation_fingerprint(copy.deepcopy(document), copy.deepcopy(shot), 'ark', 'seedream', 1)
    shot['uiPosition'] = {'x': 99, 'y': 22}
    shot['runtimeTimestamp'] = 999
    assert first == second == build_generation_fingerprint(document, shot, 'ark', 'seedream', 1)
    assert len(first['hash']) == 64 and first['algorithm'] == 'sha256'


def test_each_generation_dependency_changes_fingerprint_and_marks_stale():
    document, shot = fixture()
    original = build_generation_fingerprint(document, shot, 'ark', 'seedream', 1)
    variants = []
    changed_shot = copy.deepcopy(shot); changed_shot['action'] = '停下'
    variants.append(build_generation_fingerprint(document, changed_shot, 'ark', 'seedream', 1))
    changed_binding = copy.deepcopy(shot); changed_binding['assetBindings']['characters'][0]['versionId'] = 'hero-v2'
    variants.append(build_generation_fingerprint(document, changed_binding, 'ark', 'seedream', 1))
    changed_style = copy.deepcopy(document); changed_style['filmBible']['styleVersion'] = 8
    variants.append(build_generation_fingerprint(changed_style, shot, 'ark', 'seedream', 1))
    variants.append(build_generation_fingerprint(document, shot, 'ark', 'seedream', 2))
    assert build_generation_fingerprint(document, shot, 'ignored-legacy-provider', 'seedream', 1) == original
    variants.append(build_generation_fingerprint(document, shot, 'ark', 'other-model', 1))
    assert len({item['hash'] for item in variants}) == 5
    assert all(item['hash'] != original['hash'] for item in variants)
    assert fingerprint_status(original, original) == 'current'
    assert all(fingerprint_status(original, item) == 'stale' for item in variants)


def test_fingerprint_reads_canonical_production_context():
    document, shot = fixture()
    full = build_generation_fingerprint(document, shot, 'ark', 'seedream', 1)
    episode = {'schemaVersion': 3, 'shots': [shot]}
    context = {
        'schemaVersion': 1,
        'style': document['style'],
        'filmBible': document['filmBible'],
        'generationPolicy': {'text': None, 'image': None, 'video': None},
    }
    projected = build_generation_fingerprint(
        episode, shot, 'ark', 'seedream', 1, production_context=context,
    )
    assert projected == full
