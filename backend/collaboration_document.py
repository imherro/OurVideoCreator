"""Read-only document projection of P5 independent objects.

The legacy editor/compiler shape is an adapter, not a second writable source.
Objects are passed in by the scoped repository. No writes or migrations here.
"""
from __future__ import annotations

import copy
import json


def object_content(row):
    value = row['content']
    return json.loads(value) if isinstance(value, str) else copy.deepcopy(value)


def object_key(row):
    value = object_content(row)
    kind = row['kind']
    if kind == 'shot':
        return str(value['shot'].get('uid') or value['shot']['id'])
    if kind == 'node':
        return str(value['node']['id'])
    if kind == 'visual_card':
        return str(value['card']['id'])
    return kind


def legacy_projection(timeline):
    track = next((track for track in timeline.get('tracks', [])
                  if track.get('type') == 'video' or (track.get('type') == 'element'
                  and any(item.get('type') in {'video', 'image'} for item in track.get('elements', [])))), {})
    clips = []
    for element in track.get('elements', []):
        if element.get('type') not in {'video', 'image'}:
            continue
        props = element.get('props') or {}
        metadata = element.get('metadata') or {}
        clips.append({'id': element['id'], 'asset_id': metadata.get('assetId') or props.get('srcAssetId') or '',
                      'start': props.get('time') or 0, 'duration': max(0, element['e'] - element['s']),
                      'volume': props.get('volume', 1)})
        if props.get('playbackRate', 1) != 1:
            clips[-1]['playbackRate'] = props['playbackRate']
    return clips


def compose(episode_metadata, production_context, rows):
    """Return episode content + shared context using objects as the ONLY source.

    Strip old carriers even if a stale snapshot was accidentally left in a
    metadata column. Canonical scripts are projected separately by adaptation.
    """
    episode = copy.deepcopy(episode_metadata)
    for key in ('nodes', 'edges', 'shots', 'timeline', 'editor', 'director', 'audio_id',
                'music_volume', 'transition', 'export_resolution',
                'filmBible', 'style', 'generationPolicy', 'applied', 'viewport', 'selection',
                'selected', 'playhead', 'panel', 'panoramaViewpoint'):
        episode.pop(key, None)
    context = copy.deepcopy(production_context)
    film = context.setdefault('filmBible', {})
    film['visual'] = {'cards': {}, 'versions': {}}
    film['voices'] = {'profiles': {}}
    nodes, shots = [], []
    graph, timeline, director = {}, {'version': 2, 'tracks': []}, {}
    node_ids, shot_ids, card_ids, version_ids = set(), set(), set(), set()

    def add_node(node):
        if node['id'] in node_ids:
            raise ValueError('对象聚合发现重复节点编号')
        node_ids.add(node['id'])
        value = copy.deepcopy(node)
        for field in ('selected', 'dragging', 'resizing', 'measured', 'width', 'height', 'position'):
            value.pop(field, None)
        nodes.append(value)

    for row in rows:
        content = object_content(row)
        kind = row['kind']
        if kind == 'shot':
            key = object_key(row)
            if key in shot_ids:
                raise ValueError('对象聚合发现重复镜头编号')
            shot_ids.add(key)
            shots.append(copy.deepcopy(content['shot']))
            for node in content.get('nodes', []):
                add_node(node)
        elif kind == 'node':
            add_node(content['node'])
        elif kind == 'visual_card':
            card = content['card']
            if card['id'] in card_ids:
                raise ValueError('对象聚合发现重复视觉卡编号')
            card_ids.add(card['id'])
            film['visual']['cards'][card['id']] = copy.deepcopy(card)
            for version_id, version in content.get('versions', {}).items():
                if version_id in version_ids or version.get('cardId') != card['id']:
                    raise ValueError('视觉版本重复或所属卡片不匹配')
                version_ids.add(version_id)
                film['visual']['versions'][version_id] = copy.deepcopy(version)
            if content.get('voice_profile'):
                if content['voice_profile'].get('cardId') != card['id']:
                    raise ValueError('固定音色所属卡片不匹配')
                film['voices']['profiles'][card['id']] = copy.deepcopy(content['voice_profile'])
        elif kind == 'graph':
            graph = content
        elif kind == 'timeline':
            timeline = content['timeline']
        elif kind == 'director':
            director = content['stage']
        else:
            raise ValueError('未知协作对象类型')
    # Virtual visual nodes are read projections. Include their stable IDs here
    # so graph positions survive a fresh GET/relogin before the UI derives edges.
    for version_id, version in film['visual']['versions'].items():
        card=film['visual']['cards'][version['cardId']]
        add_node({'id':'visual-version:'+version_id,'type':'visualAsset','hidden':bool(card.get('deletedAt')),
                  'data':{'kind':'visual_asset','visualVersionId':version_id,'managed':True}})
    shot_order = {key: index for index, key in enumerate(graph.get('shotOrder', []))}
    shots.sort(key=lambda shot: (shot_order.get(str(shot.get('uid') or shot['id']), len(shot_order)),
                                 str(shot.get('uid') or shot['id'])))
    for index, shot in enumerate(shots):
        shot['order'] = index + 1
    node_order = {key: index for index, key in enumerate(graph.get('nodeOrder', []))}
    nodes.sort(key=lambda node: (node_order.get(node['id'], len(node_order)), node['id']))
    for node in nodes:
        node['position'] = copy.deepcopy(graph.get('positions', {}).get(node['id'], {'x': 0, 'y': 0}))
    episode.update(nodes=nodes, shots=shots, edges=copy.deepcopy(graph.get('edges', [])),
                   timeline=legacy_projection(timeline), editor={'version': 1, 'timeline': copy.deepcopy(timeline)},
                   director=copy.deepcopy(director))
    settings=timeline.get('ovcExport') or {}
    episode.update({key:copy.deepcopy(settings[key]) for key in ('music_volume','transition','export_resolution') if key in settings})
    music=next((element for track in timeline.get('tracks',[]) for element in track.get('elements',[])
                if (element.get('metadata') or {}).get('role')=='background-music'),{})
    episode['audio_id']=(music.get('metadata') or {}).get('assetId') or (music.get('props') or {}).get('srcAssetId') or ''
    episode['music_volume']=(music.get('props') or {}).get('volume',settings.get('music_volume',0.3))
    return episode, context
