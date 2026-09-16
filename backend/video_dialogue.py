"""Compile canonical storyboard dialogue into video-generation prompts."""
from __future__ import annotations

import math


MARKER = '[对白与声音]'
TIMING_MARKER = '[固定对白音轨时序]'
DURATION_MARKER = '[镜头时长]'


def _apply_duration(result, duration, planned_duration=None, parameter_rules=None):
    duration = max(1, int(math.ceil(float(duration))))
    base = str(result.get('prompt') or '').split(DURATION_MARKER, 1)[0].rstrip()
    result['prompt'] = (
        base + f'\n\n{DURATION_MARKER}\n'
        f'本镜头成片总时长必须为 {duration:g} 秒；所有动作、运镜、开口与闭口必须在这段时间内完成。'
    )
    result['planned_shot_duration'] = float(planned_duration if planned_duration is not None else duration)
    result['shot_duration'] = duration
    if parameter_rules is None or 'duration' in parameter_rules:
        result['parameters'] = {**(result.get('parameters') or {}), 'duration': duration}
    return result


def _shot_for_video_node(document, node_id):
    return next((
        shot for shot in document.get('shots', [])
        if shot.get('videoNode') == node_id
        or (shot.get('pipeline') or {}).get('videoNodeId') == node_id
    ), None)


def compile_video_prompt(base_prompt, shot):
    """Append exact structured dialogue without duplicating an older projection."""
    base = str(base_prompt or '').split(MARKER, 1)[0].rstrip()
    dialogues = [
        item for item in (shot.get('dialogues') or [])
        if isinstance(item, dict) and str(item.get('text') or '').strip()
    ]
    if not dialogues:
        return base
    if all(str(item.get('text') or '').strip() in base for item in dialogues):
        return base
    lines = [
        base,
        '',
        MARKER,
        '以下台词必须按原文说出，人物口型、开口时机和情绪与台词同步；不得改词、漏词或增加额外对白。',
    ]
    for index, dialogue in enumerate(dialogues, 1):
        name = str(dialogue.get('characterName') or f'角色{index}').strip()
        emotion = str(dialogue.get('emotion') or '').strip()
        text = str(dialogue.get('text') or '').strip().replace('“', '「').replace('”', '」')
        qualifier = f'（{emotion}）' if emotion else ''
        lines.append(f'{index}. {name}{qualifier}说：“{text}”')
    lines.append('没有台词的角色保持闭嘴；保留分镜要求的环境声和动作声，不生成字幕。')
    return '\n'.join(lines).strip()


def compile_shot_video_input(document, node_id, kind, input_value, production_context=None, parameter_rules=None):
    """Freeze canonical shot timing and dialogue into every video submission."""
    result = dict(input_value)
    if kind != 'video':
        return result
    if production_context is not None:
        from .production_context import compose_project_document
        document = compose_project_document(document, production_context)
    shot = _shot_for_video_node(document, node_id)
    if not shot:
        return result
    try:
        shot_duration = float(shot.get('duration'))
    except (TypeError, ValueError):
        shot_duration = 0
    if shot_duration <= 0:
        raise ValueError('分镜时长无效，请先在分镜卡片中设置大于 0 秒的时长')
    configured_duration = document.get('videoDuration', -1)
    try:
        configured_duration = int(configured_duration)
    except (TypeError, ValueError):
        configured_duration = -1
    provider_duration = configured_duration if 4 <= configured_duration <= 30 else max(1, int(math.ceil(shot_duration)))
    base_prompt = str(result.get('prompt') or shot.get('video_prompt') or '')
    # Job prompts are immutable snapshots, but this also keeps retries and old
    # already-compiled node data idempotent.
    base_prompt = base_prompt.split(DURATION_MARKER, 1)[0].rstrip()
    result['prompt'] = compile_video_prompt(
        base_prompt, shot,
    )
    result = _apply_duration(result, provider_duration, shot_duration, parameter_rules)
    dialogues = [item for item in (shot.get('dialogues') or []) if isinstance(item, dict) and str(item.get('text') or '').strip()]
    if dialogues:
        result['dialogue_projection'] = {
            'version': 'shot-dialogue/v1',
            'shotUid': str(shot.get('uid') or shot.get('id') or ''),
            'dialogues': [
                {
                    'id': str(item.get('id') or ''),
                    'characterCardId': str(item.get('characterCardId') or ''),
                    'characterName': str(item.get('characterName') or ''),
                    'emotion': str(item.get('emotion') or ''),
                    'text': str(item.get('text') or ''),
                }
                for item in dialogues
            ],
        }
    else:
        result.pop('dialogue_projection', None)
    return result


def bind_fixed_dialogue_audio(document, node_id, kind, input_value, assets, production_context=None, parameter_rules=None):
    """Freeze current locked-voice dialogue takes into a video job."""
    result = dict(input_value)
    if kind != 'video':
        return result
    if production_context is not None:
        from .production_context import compose_project_document
        document = compose_project_document(document, production_context)
    shot = _shot_for_video_node(document, node_id)
    if not shot:
        return result
    dialogues = [
        item for item in (shot.get('dialogues') or [])
        if isinstance(item, dict) and str(item.get('text') or '').strip()
    ]
    if not dialogues:
        result.pop('dialogue_audio_asset_ids', None)
        result.pop('dialogue_audio', None)
        result.pop('dialogue_audio_mode', None)
        return result
    profiles = (((document.get('filmBible') or {}).get('voices') or {}).get('profiles') or {})
    candidates = sorted(assets or [], key=lambda item: float(item.get('created') or 0), reverse=True)
    selected = []
    for dialogue in dialogues:
        card_id = str(dialogue.get('characterCardId') or '')
        profile = profiles.get(card_id) or {}
        if profile.get('status') != 'locked' or not str(profile.get('voiceType') or '').strip():
            name = str(dialogue.get('characterName') or '角色')
            raise ValueError(f'{name}尚未锁定固定音色，请先在塑角造景中设置并锁定')
        version = int(profile.get('version') or 1)
        match = next((asset for asset in candidates if (
            asset.get('kind') == 'audio'
            and ((asset.get('metadata') or {}).get('input') or {}).get('dialogue', {}).get('id') == dialogue.get('id')
            and int((((asset.get('metadata') or {}).get('input') or {}).get('dialogue', {}).get('voiceVersion') or 0)) == version
        )), None)
        if not match:
            name = str(dialogue.get('characterName') or '角色')
            raise ValueError(f'{name}的本镜对白尚未使用当前固定音色生成，请先生成本集对白')
        duration = float((match.get('metadata') or {}).get('duration') or 0)
        if duration <= 0:
            raise ValueError(f'对白音频“{match.get("name") or match.get("id")}”时长无效，请重新生成')
        selected.append((dialogue, profile, match, duration))
    shot_duration = max(
        float(shot.get('duration') or 0),
        float((result.get('parameters') or {}).get('duration') or 0),
        float(result.get('shot_duration') or 0),
    )
    gaps = max(0, len(selected) - 1) * .12
    spoken_duration = sum(item[3] for item in selected) + gaps
    effective_duration = max(shot_duration, math.ceil(spoken_duration))
    if effective_duration > shot_duration:
        result['duration_adjustment'] = {
            'reason': 'dialogue_audio',
            'from': shot_duration,
            'to': effective_duration,
            'spoken_duration': round(spoken_duration, 3),
        }
    result = _apply_duration(result, effective_duration, shot_duration, parameter_rules)
    cursor = min(.3, max(0, (effective_duration - spoken_duration) / 2)) if effective_duration else .3
    frozen = []
    timing_lines = []
    for dialogue, profile, asset, duration in selected:
        start = round(cursor, 3)
        end = round(cursor + duration, 3)
        frozen.append({
            'dialogueId': str(dialogue.get('id') or ''),
            'characterCardId': str(dialogue.get('characterCardId') or ''),
            'characterName': str(dialogue.get('characterName') or ''),
            'assetId': str(asset['id']),
            'voiceType': str(profile.get('voiceType') or ''),
            'voiceVersion': int(profile.get('version') or 1),
            'start': start,
            'duration': round(duration, 3),
        })
        timing_lines.append(f'{dialogue.get("characterName") or "角色"}从约 {start:.2f} 秒开口，到约 {end:.2f} 秒结束并自然闭嘴。')
        cursor = end + .12
    base = str(result.get('prompt') or '').split(TIMING_MARKER, 1)[0].rstrip()
    result['prompt'] = base + '\n\n' + TIMING_MARKER + '\n' + '\n'.join(timing_lines)
    result['dialogue_audio_asset_ids'] = [item['assetId'] for item in frozen]
    result['dialogue_audio'] = frozen
    # Seedance 2.5 can use the locked TTS take as a full-modal audio reference.
    # Keep the source asset ids in the durable job input; the provider builds a
    # short timing-aware reference track immediately before submission.
    result['dialogue_audio_mode'] = 'seedance_reference'
    if parameter_rules is not None and 'generate_audio' not in parameter_rules:
        raise ValueError('所选平台模型未发布固定对白所需的 generate_audio 参数')
    result['parameters'] = {**(result.get('parameters') or {}), 'generate_audio': True}
    return result
