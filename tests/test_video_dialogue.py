import pytest

from backend.video_dialogue import MARKER, bind_fixed_dialogue_audio, compile_shot_video_input, compile_video_prompt


def shot():
    return {
        'id': 'shot-001', 'uid': 'shot-uid',
        'duration': 5,
        'pipeline': {'videoNodeId': 'video-node'},
        'video_prompt': '机器人抬头，镜头缓慢推进。',
        'dialogues': [
            {'id': 'd1', 'characterCardId': 'robot', 'characterName': '球球', 'emotion': '坚定', 'text': '下一步直接拔电源。'},
            {'id': 'd2', 'characterCardId': 'human', 'characterName': '林岚', 'emotion': '', 'text': '你确定吗？'},
        ],
    }


def test_video_prompt_contains_every_exact_dialogue_and_direction():
    value = compile_video_prompt('机器人抬头，镜头缓慢推进。', shot())
    assert '球球（坚定）说：“下一步直接拔电源。”' in value
    assert '林岚说：“你确定吗？”' in value
    assert '口型' in value and '不得改词' in value and '不生成字幕' in value


def test_video_prompt_projection_replaces_older_projection_without_duplication():
    once = compile_video_prompt('基础动作', shot())
    twice = compile_video_prompt(once, shot())
    assert twice == once
    assert twice.count(MARKER) == 1


def test_video_job_compiles_dialogue_for_existing_node_and_records_projection():
    current_shot = {**shot(), 'duration': 2}
    value = compile_shot_video_input({'shots': [current_shot]}, 'video-node', 'video', {'prompt': '旧节点提示词'})
    assert value['prompt'].startswith('旧节点提示词')
    assert '本镜头成片总时长必须为 2 秒' in value['prompt']
    assert value['shot_duration'] == 2
    assert value['parameters']['duration'] == 2
    assert value['shot_video_projection'] == {'version': 'shot-video/v1', 'shotUid': 'shot-uid', 'sourcePrompt': '旧节点提示词'}
    assert value['dialogue_projection']['shotUid'] == 'shot-uid'
    assert value['dialogue_projection']['dialogues'][0]['text'] == '下一步直接拔电源。'


def test_video_job_canonical_duration_overrides_provider_or_stale_node_default():
    current_shot = {**shot(), 'duration': 2}
    value = compile_shot_video_input(
        {'shots': [current_shot]}, 'video-node', 'video',
        {'prompt': '两秒镜头', 'parameters': {'duration': 5, 'resolution': '480p'}},
    )
    assert value['parameters'] == {'duration': 2, 'resolution': '480p'}
    assert value['prompt'].count('[镜头时长]') == 1
    repeated = compile_shot_video_input({'shots': [current_shot]}, 'video-node', 'video', value)
    assert repeated['parameters']['duration'] == 2
    assert repeated['prompt'].count('[镜头时长]') == 1


def test_project_video_duration_can_explicitly_override_shot_duration():
    current_shot = {**shot(), 'duration': 2}
    value = compile_shot_video_input(
        {'shots': [current_shot], 'videoDuration': 8}, 'video-node', 'video',
        {'prompt': '项目固定八秒'},
    )
    assert value['parameters']['duration'] == 8
    assert value['planned_shot_duration'] == 2
    assert '成片总时长必须为 8 秒' in value['prompt']


def test_non_video_and_unbound_nodes_are_unchanged():
    original = {'prompt': '保持不变'}
    assert compile_shot_video_input({'shots': [shot()]}, 'video-node', 'image', original) == original
    assert compile_shot_video_input({'shots': [shot()]}, 'other-node', 'video', original) == original


def test_shot_video_marker_is_server_owned_and_never_retained_on_unbound_nodes():
    original = {'prompt': 'source', 'shot_video_projection': {'version': 'shot-video/v1', 'sourcePrompt': 'forged'}}
    for kind, node_id in [('image', 'video-node'), ('video', 'other-node')]:
        assert compile_shot_video_input({'shots': [shot()]}, node_id, kind, original) == {'prompt': 'source'}
    doc = {'shots': [shot()], 'nodes': [{'id': 'video-node', 'data': {'prompt': 'canonical'}}]}
    compiled = compile_shot_video_input(doc, 'video-node', 'video', original)
    assert compiled['shot_video_projection']['sourcePrompt'] == 'canonical'
    assert original['shot_video_projection']['sourcePrompt'] == 'forged'


def test_locked_voice_dialogue_assets_are_frozen_into_video_input():
    value = shot()
    document = {
        'shots': [value],
        'filmBible': {'voices': {'profiles': {
            'robot': {'status': 'locked', 'voiceType': 'robot-speaker', 'version': 2},
            'human': {'status': 'locked', 'voiceType': 'human-speaker', 'version': 4},
        }}},
    }
    assets = [
        {'id': 'old-robot', 'kind': 'audio', 'created': 1, 'metadata': {'duration': 1, 'input': {'dialogue': {'id': 'd1', 'voiceVersion': 1}}}},
        {'id': 'robot-audio', 'kind': 'audio', 'created': 2, 'metadata': {'duration': 1.4, 'input': {'dialogue': {'id': 'd1', 'voiceVersion': 2}}}},
        {'id': 'human-audio', 'kind': 'audio', 'created': 3, 'metadata': {'duration': 1.1, 'input': {'dialogue': {'id': 'd2', 'voiceVersion': 4}}}},
    ]
    with pytest.raises(ValueError,match='明确采纳'):
        bind_fixed_dialogue_audio(document, 'video-node', 'video', {'prompt': '基础动作'}, assets)
    for dialogue,asset in zip(value['dialogues'],assets[1:]):
        dialogue.update(audioAssetId=asset['id'],audioVoiceVersion=asset['metadata']['input']['dialogue']['voiceVersion'])
        asset['metadata']['input']['dialogue']['text']=dialogue['text']
    # A newer successful candidate is not the selected take.
    assets.append({**assets[1],'id':'new-unadopted','created':999})
    result = bind_fixed_dialogue_audio(document, 'video-node', 'video', {'prompt': '基础动作'}, assets)
    assert result['dialogue_audio_asset_ids'] == ['robot-audio', 'human-audio']
    assert result['dialogue_audio'][0]['voiceType'] == 'robot-speaker'
    assert result['dialogue_audio'][1]['start'] > result['dialogue_audio'][0]['start']
    assert result['dialogue_audio_mode'] == 'seedance_reference'
    assert result['parameters']['generate_audio'] is True
    assert '固定对白音轨时序' in result['prompt'] and '自然闭嘴' in result['prompt']


def test_dialogue_longer_than_planned_shot_extends_generation_to_next_second():
    current_shot = {**shot(), 'duration': 2}
    document = {
        'shots': [current_shot],
        'filmBible': {'voices': {'profiles': {
            'robot': {'status': 'locked', 'voiceType': 'robot-speaker', 'version': 2},
            'human': {'status': 'locked', 'voiceType': 'human-speaker', 'version': 4},
        }}},
    }
    assets = [
        {'id': 'robot-audio', 'kind': 'audio', 'created': 2, 'metadata': {'duration': 1.4, 'input': {'dialogue': {'id': 'd1', 'voiceVersion': 2}}}},
        {'id': 'human-audio', 'kind': 'audio', 'created': 3, 'metadata': {'duration': 1.1, 'input': {'dialogue': {'id': 'd2', 'voiceVersion': 4}}}},
    ]
    for dialogue,asset in zip(current_shot['dialogues'],assets):
        dialogue.update(audioAssetId=asset['id'],audioVoiceVersion=asset['metadata']['input']['dialogue']['voiceVersion'])
        asset['metadata']['input']['dialogue']['text']=dialogue['text']
    result = bind_fixed_dialogue_audio(document, 'video-node', 'video', {'prompt': '基础动作'}, assets)
    assert result['parameters']['duration'] == 3
    assert result['shot_duration'] == 3
    assert result['duration_adjustment'] == {
        'reason': 'dialogue_audio', 'from': 2.0, 'to': 3, 'spoken_duration': 2.62,
    }
    assert '成片总时长必须为 3 秒' in result['prompt']


def test_video_with_dialogue_requires_current_locked_voice_take():
    document = {'shots': [shot()], 'filmBible': {'voices': {'profiles': {}}}}
    with pytest.raises(ValueError, match='尚未锁定固定音色'):
        bind_fixed_dialogue_audio(document, 'video-node', 'video', {'prompt': '动作'}, [])
    document['filmBible']['voices']['profiles'] = {
        'robot': {'status': 'locked', 'voiceType': 'robot', 'version': 1},
        'human': {'status': 'locked', 'voiceType': 'human', 'version': 1},
    }
    with pytest.raises(ValueError, match='尚未使用当前固定音色生成'):
        bind_fixed_dialogue_audio(document, 'video-node', 'video', {'prompt': '动作'}, [])
