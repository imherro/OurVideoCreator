"""Pure Project.document migrations. Database history is never rewritten here."""
from __future__ import annotations

import copy
import json
import uuid

CURRENT_SCHEMA_VERSION = 6

def empty_film_bible():
    return {
        'visual': {'cards': {}, 'versions': {}},
        'continuity': {},
        'style': {},
        'styleVersion': 1,
        'story': {},
        'voices': {'profiles': {}},
    }

def empty_generation_policy():
    return {'text': None, 'image': None, 'video': None}

def new_document(generation_policy=None):
    return {
        'schemaVersion': CURRENT_SCHEMA_VERSION,
        'filmBible': empty_film_bible(),
        'generationPolicy': copy.deepcopy(generation_policy or empty_generation_policy()),
        'nodes': [], 'edges': [], 'shots': [], 'timeline': [], 'characters': [],
        'brief': '', 'style': '电影写实', 'ratio': '16:9', 'duration': 120,
        'videoResolution': '720p',
        'videoRatio': '16:9', 'videoDuration': -1, 'videoFormat': 'mp4',
    }

def _migrate_v0_to_v1(value):
    film = value.setdefault('filmBible', {})
    visual = film.setdefault('visual', {})
    visual.setdefault('cards', {})
    visual.setdefault('versions', {})
    film.setdefault('continuity', {})
    film.setdefault('style', {})
    film.setdefault('story', {})
    policy = value.setdefault('generationPolicy', empty_generation_policy())
    for kind in ('text', 'image', 'video'):
        policy.setdefault(kind, None)
    # Phase 0 only adds schema foundations; all legacy product fields survive.
    for key, default in (('nodes', []), ('edges', []), ('shots', []), ('timeline', []), ('characters', [])):
        value.setdefault(key, copy.deepcopy(default))
    value['schemaVersion'] = 1
    return value

def _migrate_v1_to_v2(value):
    for index,shot in enumerate(value.get('shots') or []):
        if not isinstance(shot,dict):continue
        if not shot.get('uid'):
            identity=json.dumps({k:shot.get(k) for k in ('id','scene','characters','action','camera','image_prompt')},ensure_ascii=False,sort_keys=True)+f':{index}'
            shot['uid']='shot-'+uuid.uuid5(uuid.NAMESPACE_URL,'my-video-creator:'+identity).hex
        shot.setdefault('order',index+1)
        shot.setdefault('assetBindings',{'characters':[],'scene':None,'props':[]})
        shot.setdefault('pipeline',{'imageNodeId':shot.get('imageNode'),'videoNodeId':shot.get('videoNode')})
    value['schemaVersion']=2
    return value

def _migrate_v2_to_v3(value):
    # Style content and its identity evolve independently. Existing projects
    # start at version 1 without rewriting any style value or old revision.
    film=value.setdefault('filmBible',{})
    film.setdefault('styleVersion',1)
    value['schemaVersion']=3
    return value

def _migrate_v3_to_v4(value):
    value.setdefault('videoResolution','720p')
    value['schemaVersion']=4
    return value

def _migrate_v4_to_v5(value):
    film=value.setdefault('filmBible',{})
    voices=film.setdefault('voices',{})
    voices.setdefault('profiles',{})
    value['schemaVersion']=5
    return value

def _migrate_v5_to_v6(value):
    value.setdefault('videoRatio', value.get('ratio', '16:9'))
    value.setdefault('videoDuration', -1)
    value.setdefault('videoFormat', 'mp4')
    value['schemaVersion']=6
    return value

def migrate_document(document):
    """Return a migrated copy. Reject future schemas rather than downgrading."""
    source = document if isinstance(document, dict) else {}
    version = source.get('schemaVersion', 0)
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise ValueError('项目 Schema 版本无效')
    if version > CURRENT_SCHEMA_VERSION:
        raise ValueError('此项目由更新版本的 MyVideoCreator 创建，请升级程序后再打开')
    value = copy.deepcopy(source)
    while version < CURRENT_SCHEMA_VERSION:
        if version == 0:
            value = _migrate_v0_to_v1(value)
            version = 1
        elif version == 1:
            value = _migrate_v1_to_v2(value)
            version = 2
        elif version == 2:
            value = _migrate_v2_to_v3(value)
            version = 3
        elif version == 3:
            value = _migrate_v3_to_v4(value)
            version = 4
        elif version == 4:
            value = _migrate_v4_to_v5(value)
            version = 5
        elif version == 5:
            value = _migrate_v5_to_v6(value)
            version = 6
        else:
            raise ValueError(f'缺少项目 Schema v{version} 的迁移程序')
    return value
