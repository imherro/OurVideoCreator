"""Freeze the exact text prompt contract used by a durable job."""
from __future__ import annotations

import copy

IMAGE_SYSTEM_PROMPT = """你是安影的影视分镜美术生成器。严格依据用户提示词、项目视觉风格和按顺序提供的独立参考图生成单张画面。参考图用于锁定角色身份、服装、场景结构和道具外观；只改变镜头明确要求的动作、表情、构图与光线。不要添加提示词未要求的文字、水印或拼贴。"""

VIDEO_SYSTEM_PROMPT = """你是安影的影视镜头生成器。严格依据用户提示词和首帧/尾帧参考生成连续视频，保持人物身份、服装、场景、道具和空间关系稳定。提示词中的对白必须由指定角色按原文说出，声音、开口时机、情绪和口型自然同步，不得改词、漏词或增加额外对白；没有台词的角色保持闭嘴。动作与摄影机运动应符合镜头描述，避免闪烁、形变、身份漂移、额外人物、字幕、文字和水印。"""

AUDIO_SYSTEM_PROMPT = """你是安影的角色对白合成器。严格使用角色 Film Bible 中已选择的固定音色和本次台词参数生成音频，不改变台词内容，不在前后添加说明、音乐或额外对白。"""


def freeze_prompt_contract(kind: str, value: dict, *, origin: str = 'submission') -> dict:
    result = copy.deepcopy(value)
    stage = result.get('stage')
    system_prompt = None
    response_schema = None
    schema_version = None

    if stage == 'source_analysis':
        from .source_library import EVENT_SCHEMA, SYSTEM_PROMPT
        system_prompt, response_schema, schema_version = SYSTEM_PROMPT, EVENT_SCHEMA, 'source-events/v1'
    elif stage == 'adaptation_generation':
        from .adaptation import ADAPTATION_SCHEMA, ADAPTATION_SYSTEM_PROMPT
        system_prompt, response_schema, schema_version = ADAPTATION_SYSTEM_PROMPT, ADAPTATION_SCHEMA, 'adaptation-plan/v1'
    elif stage == 'script_generation':
        from .adaptation import SCRIPT_SCHEMA, SCRIPT_SYSTEM_PROMPT
        system_prompt, response_schema, schema_version = SCRIPT_SYSTEM_PROMPT, SCRIPT_SCHEMA, 'episode-script/v2'
    elif kind == 'storyboard' and result.get('film_bible'):
        from .film_bible.reuse import visual_user_prompt
        from .film_bible.models import (
            BOUND_STORYBOARD_SCHEMA, STORYBOARD_DIRECTOR_PROMPT,
            VISUAL_BIBLE_SCHEMA, VISUAL_EXTRACTOR_PROMPT,
        )
        context = result.get('storyboard_visual_context') or {}
        # The durable contract is server-owned. Rebuild it after the canonical
        # collaborative visual snapshot has been frozen; never retain a caller
        # supplied catalog or stage prompt.
        result['prompt_stages'] = [
            {
                'id': 'visual_bible', 'label': '阶段 1 · 提取视觉资产卡',
                'system_prompt': VISUAL_EXTRACTOR_PROMPT,
                'user_prompt': visual_user_prompt(result.get('prompt', ''), context.get('visual')),
                'response_schema': VISUAL_BIBLE_SCHEMA,
                'schema_version': 'visual-bible/v2' if context else 'visual-bible/v1',
            },
            {
                'id': 'bound_storyboard', 'label': '阶段 2 · 生成绑定分镜',
                'system_prompt': STORYBOARD_DIRECTOR_PROMPT,
                'user_prompt_template': '剧本：\n{{script}}\n\n只允许引用以下视觉卡：\n{{visual_cards_json}}\n{{duration_constraint}}',
                'response_schema': BOUND_STORYBOARD_SCHEMA,
                'schema_version': 'bound-storyboard/v2',
            },
        ]
        schema_version = 'film-bible-storyboard/v2' if context else 'film-bible-storyboard/v1'
    elif kind in ('text', 'storyboard'):
        from .prompts import SHOT_SCHEMA, TEMPLATES
        system_prompt = TEMPLATES[kind]
        if kind == 'storyboard':
            response_schema, schema_version = SHOT_SCHEMA, 'storyboard/v1'
    elif kind == 'image':
        system_prompt, schema_version = IMAGE_SYSTEM_PROMPT, 'image-generation/v1'
    elif kind == 'video':
        system_prompt, schema_version = VIDEO_SYSTEM_PROMPT, 'video-generation/v2'
    elif kind == 'audio':
        system_prompt, schema_version = AUDIO_SYSTEM_PROMPT, 'dialogue-tts/v1'

    if system_prompt is not None:
        result.setdefault('system_prompt', system_prompt)
    if response_schema is not None:
        result.setdefault('response_schema', response_schema)
        result.setdefault('schema_version', schema_version)
    if schema_version is not None:
        result.setdefault('schema_version', schema_version)
    if system_prompt is not None or response_schema is not None or result.get('prompt_stages'):
        result.setdefault('prompt_contract_origin', origin)
    return result
