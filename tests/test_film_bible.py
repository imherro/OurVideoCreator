import pytest

from backend.film_bible.validate import normalize_bound_storyboard, normalize_visual_bible


def visual_input():
    return {'cards':[
        {'key':'hero','kind':'character','name':'林岚','parent_key':'','description':'短发青年，灰色风衣','attributes':[{'name':'发型','value':'黑色短发'}],'invariants':['灰色风衣']},
        {'key':'hero_wet','kind':'character_state','name':'林岚·淋湿','parent_key':'hero','description':'风衣和头发被雨淋湿','attributes':[{'name':'衣物状态','value':'湿透'}],'invariants':['仍穿灰色风衣']},
        {'key':'alley','kind':'scene','name':'雨巷','parent_key':'','description':'夜晚狭窄石板巷','attributes':[],'invariants':['蓝色霓虹灯']},
        {'key':'umbrella','kind':'prop','name':'红伞','parent_key':'','description':'旧红色长柄伞','attributes':[],'invariants':['木质弯柄']},
    ]}


def storyboard_input(character_key='hero_wet'):
    return {'title':'雨巷','shots':[{
        'duration':5,'scene':'雨巷','characters':'林岚','action':'拾起红伞','emotion':'警觉',
        'camera':'中景缓推','audio':'雨声','image_prompt':'林岚站在红伞旁',
        'video_prompt':'林岚弯腰拾起红伞','character_keys':[character_key],
        'scene_key':'alley','prop_keys':['umbrella'],
        'dialogues':[{'character_key':'hero','text':'谁在那里？','emotion':'警觉'}],
    }]}


def test_visual_cards_create_immutable_draft_versions_and_frozen_state_parent():
    bible,keys=normalize_visual_bible(visual_input(),'ark','doubao')
    assert len(bible['cards'])==4 and len(bible['versions'])==4
    hero_card,hero_version=keys['hero'];state_card,state_version=keys['hero_wet']
    assert hero_card.startswith('vc-') and hero_version.startswith('vv-')
    assert bible['cards'][state_card]['parentCardId']==hero_card
    assert bible['versions'][state_version]['parentVersionId']==hero_version
    assert bible['versions'][state_version]['status']=='draft'
    assert bible['versions'][state_version]['references']==[]
    assert bible['versions'][state_version]['provenance']['model_id']=='doubao'
    assert all(card['source']=={'type':'script_extraction'} for card in bible['cards'].values())


def test_bound_shots_use_system_uids_and_version_bindings_only():
    bible,keys=normalize_visual_bible(visual_input())
    result=normalize_bound_storyboard(storyboard_input(),bible,keys,5)
    shot=result['shots'][0]
    assert shot['id']=='shot-001' and shot['uid'].startswith('shot-') and shot['uid']!='shot-001'
    assert shot['order']==1 and shot['pipeline']=={}
    assert shot['assetBindings']['characters'][0]['versionId']==keys['hero_wet'][1]
    assert shot['assetBindings']['scene']['versionId']==keys['alley'][1]
    assert shot['assetBindings']['props'][0]['versionId']==keys['umbrella'][1]
    assert shot['dialogues'][0]['characterCardId']==keys['hero'][0]
    assert 'character_keys' not in shot and 'scene_key' not in shot and 'prop_keys' not in shot


def test_visual_and_binding_validation_rejects_ambiguous_or_dangling_data():
    duplicate=visual_input();duplicate['cards'].append({**duplicate['cards'][0],'key':'hero_copy'})
    with pytest.raises(ValueError,match='重复语义'):normalize_visual_bible(duplicate)
    broken=visual_input();broken['cards'][1]['parent_key']='alley'
    with pytest.raises(ValueError,match='parent_key 无效'):normalize_visual_bible(broken)
    bible,keys=normalize_visual_bible(visual_input())
    with pytest.raises(ValueError,match='悬空视觉引用'):
        normalize_bound_storyboard(storyboard_input('unknown'),bible,keys)
    wrong=storyboard_input('alley')
    with pytest.raises(ValueError,match='非角色卡'):
        normalize_bound_storyboard(wrong,bible,keys)

@pytest.mark.parametrize(('field','value'),[('attributes',{}),('invariants','灰色风衣')])
def test_visual_schema_container_types_are_strict(field,value):
    malformed=visual_input();malformed['cards'][0][field]=value
    with pytest.raises(ValueError,match=field):normalize_visual_bible(malformed)

@pytest.mark.parametrize(('field','value'),[('character_keys','hero'),('prop_keys',{}),('scene_key',3),('duration','5'),('camera',9)])
def test_storyboard_schema_field_types_are_strict(field,value):
    bible,keys=normalize_visual_bible(visual_input());malformed=storyboard_input();malformed['shots'][0][field]=value
    with pytest.raises(ValueError,match=field):normalize_bound_storyboard(malformed,bible,keys)
