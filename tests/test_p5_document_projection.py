import copy

import pytest

from backend.collaboration_document import compose


def test_old_document_carriers_cannot_overwrite_object_sources():
    metadata = {'brief': 'kept', 'shots': [{'uid': 'old'}], 'nodes': [{'id': 'old'}],
                'timeline': [{'asset_id': 'old'}], 'viewport': {'zoom': 4}, 'applied': ['old']}
    context = {'style': 'film', 'filmBible': {'story': {'premise': 'kept'},
               'visual': {'cards': {'old': {}}, 'versions': {'old': {}}}}}
    rows = [
        {'kind': 'shot', 'content': {'shot': {'id': 'S01', 'uid': 'shot-x', 'order': 999},
                                    'nodes': [{'id': 'image-x', 'data': {'prompt': 'new'}, 'selected': True}]}},
        {'kind': 'graph', 'content': {'shotOrder': ['shot-x'], 'positions': {'image-x': {'x': 10, 'y': 20}}}},
        {'kind': 'visual_card', 'content': {'card': {'id': 'c', 'currentVersionId': 'v'},
          'versions': {'v': {'id': 'v', 'cardId': 'c', 'status': 'locked'}},
          'voice_profile': {'cardId': 'c', 'version': 1, 'status': 'locked'}}},
    ]
    before = copy.deepcopy((metadata, context, rows))
    episode, production = compose(metadata, context, rows)
    assert episode['brief'] == 'kept' and episode['shots'][0]['uid'] == 'shot-x'
    assert episode['shots'][0]['order'] == 1
    assert episode['nodes'][0]['position'] == {'x': 10, 'y': 20}
    assert 'selected' not in episode['nodes'][0] and 'viewport' not in episode and 'applied' not in episode
    assert episode['timeline'] == []
    assert set(production['filmBible']['visual']['cards']) == {'c'}
    assert production['filmBible']['voices']['profiles']['c']['status'] == 'locked'
    assert (metadata, context, rows) == before


def test_project_document_timeline_is_only_a_projection_with_stable_asset_identity():
    timeline = {'version': 2, 'tracks': [{'type': 'video', 'elements': [
        {'id': 'clip', 'type': 'video', 's': 0, 'e': 4,
         'props': {'time': 2, 'volume': 0.5, 'srcAssetId': 'asset-stable'}, 'metadata': {}}]}]}
    episode, _ = compose({}, {}, [{'kind': 'timeline', 'content': {'timeline': timeline}}])
    assert episode['timeline'] == [{'id': 'clip', 'asset_id': 'asset-stable', 'start': 2, 'duration': 4, 'volume': 0.5}]
    assert episode['editor']['timeline'] == timeline


def test_child_node_cannot_be_declared_independent_again():
    rows = [{'kind': 'shot', 'content': {'shot': {'id': 's'}, 'nodes': [{'id': 'n'}]}},
            {'kind': 'node', 'content': {'node': {'id': 'n'}}}]
    with pytest.raises(ValueError, match='重复节点'):
        compose({}, {}, rows)


def test_virtual_visual_positions_and_timeline_export_survive_fresh_read():
    rows=[{'kind':'visual_card','content':{'card':{'id':'card'},'versions':{'v1':{'id':'v1','cardId':'card'}}}},
          {'kind':'graph','content':{'positions':{'visual-version:v1':{'x':300,'y':75}}}},
          {'kind':'timeline','content':{'timeline':{'version':2,'ovcExport':{'transition':'fade','export_resolution':'1920x1080'},
            'tracks':[{'type':'audio','elements':[{'type':'audio','metadata':{'role':'background-music','assetId':'music'},'props':{'volume':0.7}}]}]}}}]
    episode,_=compose({'audio_id':'old','music_volume':0.1,'transition':'cut'}, {}, rows)
    assert episode['nodes'][0]['id']=='visual-version:v1'
    assert episode['nodes'][0]['position']=={'x':300,'y':75}
    assert episode['audio_id']=='music' and episode['music_volume']==0.7
    assert episode['transition']=='fade' and episode['export_resolution']=='1920x1080'
