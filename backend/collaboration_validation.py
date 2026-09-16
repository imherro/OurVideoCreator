"""Business envelopes and ownership checks for the six P5 object kinds."""
from __future__ import annotations

import json
import math

from fastapi import HTTPException

from .collaboration_document import object_content, object_key
from .film_bible.versioning import validate_film_bible_transition


ENVELOPES = {
    'shot': {'shot', 'nodes'}, 'node': {'node'},
    'visual_card': {'card', 'versions', 'voice_profile'},
    'graph': {'edges', 'positions', 'nodeOrder', 'shotOrder'},
    'timeline': {'timeline'}, 'director': {'stage'},
}


def invalid(message):
    raise HTTPException(422, message)


def identifier(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        invalid('对象语义编号必须是 1–160 字符的字符串')
    return value


def node_ids(kind, content):
    if kind == 'node':
        return {content['node']['id']}
    if kind == 'shot':
        return {node['id'] for node in content['nodes']}
    return set()


def envelope(kind, content):
    allowed = ENVELOPES.get(kind)
    if allowed is None or not isinstance(content, dict) or set(content) != allowed:
        invalid('对象内容字段与类型不匹配')
    if kind == 'shot':
        shot = content['shot']
        if not isinstance(shot, dict) or not isinstance(content['nodes'], list):
            invalid('镜头及其附属节点格式无效')
        identifier(shot.get('uid') or shot.get('id'))
        identifier(shot.get('id'))
        children = content['nodes']
        links = {value for value in (shot.get('imageNode'), shot.get('videoNode'),
                 (shot.get('pipeline') or {}).get('imageNodeId'),
                 (shot.get('pipeline') or {}).get('videoNodeId')) if value}
        if not all(isinstance(value, str) for value in links):
            invalid('镜头管线引用无效')
    elif kind == 'node':
        children = [content['node']]
    else:
        children = []
    seen = set()
    for node in children:
        if not isinstance(node, dict) or not isinstance(node.get('data'), dict):
            invalid('节点格式无效')
        nid = identifier(node.get('id'))
        if nid.startswith('visual-version:'):
            invalid('视觉版本投影编号不可用于可编辑节点')
        if nid in seen:
            invalid('附属节点编号重复')
        seen.add(nid)
        if node.get('type') == 'visualAsset' or node['data'].get('canonicalScriptProjection') or node['data'].get('managed'):
            invalid('只读投影节点不能声明为可编辑节点')
        if any(key in node for key in ('selected', 'position', 'dragging', 'measured')):
            invalid('节点位置须通过结构命令保存；选择状态属于个人界面')
    if kind == 'shot' and seen != links:
        invalid('镜头附属节点必须与其管线引用一一对应')
    if kind == 'visual_card':
        card, versions = content['card'], content['versions']
        if not isinstance(card, dict) or not isinstance(versions, dict):
            invalid('视觉卡与版本格式无效')
        key = identifier(card.get('id'))
        for version_id, version in versions.items():
            identifier(version_id)
            if not isinstance(version, dict) or version.get('id') != version_id or version.get('cardId') != key:
                invalid('视觉版本编号或所属卡片无效')
        voice = content['voice_profile']
        if voice is not None and (not isinstance(voice, dict) or voice.get('cardId') != key):
            invalid('音色必须属于当前视觉卡')
    if kind == 'timeline':
        if not isinstance(content['timeline'], dict) or not isinstance(content['timeline'].get('tracks'), list):
            invalid('时间线必须是包含 tracks 的 Twick 工程')
        settings=content['timeline'].get('ovcExport',{})
        if not isinstance(settings,dict) or set(settings)-{'transition','music_volume','export_resolution'}:
            invalid('剪辑导出设置字段无效')
        if 'transition' in settings and settings['transition'] not in {'cut','fade'}:
            invalid('剪辑转场无效')
        if 'music_volume' in settings and (not isinstance(settings['music_volume'],(int,float)) or
                isinstance(settings['music_volume'],bool) or not 0 <= settings['music_volume'] <= 1):
            invalid('背景音乐音量无效')
        if 'export_resolution' in settings and settings['export_resolution'] not in {'1280x720','1920x1080','720x1280','1080x1920','1080x1080'}:
            invalid('导出分辨率无效')
    if kind == 'director':
        if not isinstance(content['stage'], dict) or not isinstance(content['stage'].get('objects'), list) or not isinstance(content['stage'].get('camera'), dict):
            invalid('导演台须包含 objects 与 camera')
    if kind == 'graph':
        if not isinstance(content['edges'], list) or not isinstance(content['positions'], dict):
            invalid('画布结构格式无效')
        for key in ('nodeOrder', 'shotOrder'):
            values = content[key]
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values) or len(set(values)) != len(values):
                invalid('结构排序编号无效或重复')
        for key, position in content['positions'].items():
            identifier(key)
            if not isinstance(position, dict) or set(position) != {'x', 'y'} or not all(
                isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v) for v in position.values()
            ):
                invalid('节点位置必须是有限的 x/y 坐标')
        edge_ids = set()
        for edge in content['edges']:
            if not isinstance(edge, dict):
                invalid('连线格式无效')
            eid = identifier(edge.get('id'))
            identifier(edge.get('source')); identifier(edge.get('target'))
            if eid in edge_ids or (edge.get('data') or {}).get('managed') or edge.get('selected') is not None:
                invalid('连线重复、只读或包含个人选择状态')
            edge_ids.add(eid)
    return object_key({'kind': kind, 'content': content})


def structure_lock(connection, project_id):
    connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('object-structure:' + project_id,))


def ownership(connection, scope, kind, content, old=None):
    """Serialize only structural identity changes, not ordinary shot edits."""
    new_ids = node_ids(kind, content)
    previous = object_content(old) if old else None
    old_ids = node_ids(kind, previous) if previous else set()
    if old and object_key(old) != envelope(kind, content):
        invalid('对象语义编号不可修改')
    if new_ids != old_ids:
        structure_lock(connection, scope['project_id'])
        for row in connection.execute('''SELECT id,kind,content FROM collaboration_objects
            WHERE project_id=%s AND kind IN ('shot','node') AND NOT deleted ORDER BY id''', (scope['project_id'],)):
            if old and row['id'] == old['id']:
                continue
            if new_ids & node_ids(row['kind'], object_content(row)):
                invalid('节点已属于其他对象，不能借自由节点或镜头重新声明权限')
        script = connection.execute('SELECT metadata FROM episode_scripts WHERE project_id=%s', (scope['project_id'],)).fetchone()
        if script and json.loads(script['metadata']).get('projectionNodeId') in new_ids:
            invalid('正式剧本投影必须通过剧本对象修改')


def visual_transition(connection, production_id, kind, content, old=None):
    if kind not in {'shot', 'visual_card'}:
        return
    # Version identity / binding validation is short and local, never Provider I/O.
    # Binding changes and card changes share this lock so delete/bind cannot race.
    previous = object_content(old) if old else {}
    if kind == 'shot' and (previous.get('shot') or {}).get('assetBindings') == content['shot'].get('assetBindings'):
        return
    connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('visual-bindings:' + production_id,))
    before = {'filmBible': {'visual': {'cards': {}, 'versions': {}}}, 'shots': []}
    for row in connection.execute('SELECT kind,content FROM collaboration_objects WHERE production_id=%s AND NOT deleted', (production_id,)):
        value = object_content(row)
        if row['kind'] == 'visual_card':
            before['filmBible']['visual']['cards'][value['card']['id']] = value['card']
            before['filmBible']['visual']['versions'].update(value['versions'])
        elif row['kind'] == 'shot':
            before['shots'].append(value['shot'])
    import copy
    after = copy.deepcopy(before)
    if kind == 'visual_card':
        visual = after['filmBible']['visual']
        card_id = content['card']['id']
        for version_id, version in content['versions'].items():
            existing = visual['versions'].get(version_id)
            if existing and existing['cardId'] != card_id:
                invalid('视觉版本已属于其他卡片')
        visual['cards'][card_id] = content['card']
        visual['versions'] = {key: value for key, value in visual['versions'].items() if value['cardId'] != card_id}
        visual['versions'].update(content['versions'])
        prior_voice = previous.get('voice_profile')
        voice = content['voice_profile']
        if prior_voice and prior_voice.get('status') == 'locked' and voice != prior_voice:
            if not voice or voice.get('status') != 'draft' or voice.get('version', 0) <= prior_voice.get('version', 0):
                invalid('已锁定音色不可原地修改；须显式派生新音色版本')
    else:
        shot_key = content['shot'].get('uid') or content['shot']['id']
        after['shots'] = [shot for shot in after['shots'] if (shot.get('uid') or shot['id']) != shot_key]
        after['shots'].append(content['shot'])
    validate_film_bible_transition(before, after)


def graph_transition(connection, row, content, proposed=None):
    if row['kind'] != 'graph':
        return
    from . import identity
    # Layout/ordering are shared structure. Dependency edges, unlike layout,
    # alter a target's effective input and therefore require that target owner.
    owners = {}
    shot_keys = set()
    items = proposed if proposed is not None else connection.execute('''SELECT * FROM collaboration_objects WHERE production_id=%s
        AND (project_id=%s OR project_id IS NULL) AND NOT deleted''', (row['production_id'],row['project_id']))
    for item in items:
        value = object_content(item)
        for nid in node_ids(item['kind'],value):
            owners[nid] = item['assignee_id']
        if item['kind'] == 'shot':
            shot_keys.add(object_key(item))
        elif item['kind'] == 'visual_card':
            for vid in value['versions']:
                owners['visual-version:' + vid] = item['assignee_id']
    script = connection.execute('SELECT metadata FROM episode_scripts WHERE project_id=%s',(row['project_id'],)).fetchone()
    if script:
        projection_id = json.loads(script['metadata']).get('projectionNodeId')
        if projection_id:
            owners[projection_id] = None # Read-only source, never an editable target.
    if set(content['positions']) - set(owners) or set(content['nodeOrder']) - set(owners):
        invalid('画布结构引用了不存在或其他分集的节点')
    if set(content['shotOrder']) - shot_keys:
        invalid('画布排序引用了不存在或其他分集的镜头')
    old_edges = {edge['id']:edge for edge in object_content(row)['edges']}
    new_edges = {edge['id']:edge for edge in content['edges']}
    prior_owners=dict(owners)
    if proposed is not None:
        for prior in connection.execute('''SELECT * FROM collaboration_objects WHERE project_id=%s
            AND kind IN ('shot','node') AND NOT deleted''',(row['project_id'],)):
            for nid in node_ids(prior['kind'],object_content(prior)):
                prior_owners[nid]=prior['assignee_id']
    for edge in new_edges.values():
        if edge['source'] not in owners or edge['target'] not in owners:
            invalid('画布连线的源或目标不存在')
    for edge_id in old_edges.keys() | new_edges.keys():
        if old_edges.get(edge_id) == new_edges.get(edge_id):
            continue
        for edge, owner_map in ((old_edges.get(edge_id),prior_owners),(new_edges.get(edge_id),owners)):
            if edge and owner_map.get(edge['target']) != identity.current().user_id:
                raise HTTPException(403,'修改依赖连线需要目标对象编辑权')
