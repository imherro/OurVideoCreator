"""Named locked voices and state selection through real scoped PostgreSQL objects."""
from copy import deepcopy
import uuid
import pytest
from backend import store as s
from backend.providers.common import register
from backend.voice_resolution import locked_versions,voice_snapshot,resolved_voice
from tests.test_p5_object_transactions import team,admin,clients,clear_auth_rate_limits,url,version,save,create
from tests.test_p5_object_candidates import candidate,audio_result
from tests.test_voice_samples import confirmed_voice,sample_shot,submit_sample


def library(team,tmp_path):
    card,first=confirmed_voice(team,tmp_path)
    content=deepcopy(card['content']);voice=content['voice_profile']
    voice.update(defaultVersion=1,lockedVersions=locked_versions(voice))
    result=save(team,card,content);assert result.status_code==200,result.text;card=result.json()
    content=deepcopy(card['content']);voice=content['voice_profile']
    voice.update(version=2,status='draft',name='变身女声',previewText='second audition')
    for key in ('referenceAssetId','referenceVersion','previewAssetId','generationJobId'):voice.pop(key,None)
    result=save(team,card,content);assert result.status_code==200,result.text;card=result.json()
    result=team['a'].post('/api/projects/'+team['pid']+'/jobs',json={'kind':'audio','node_id':'voice-profile:hero','submission_id':uuid.uuid4().hex,
        'input':{'model_id':voice['model_id'],'voice_type':voice['voiceType'],'prompt':voice['previewText'],'voice_profile':{'cardId':'hero','version':2}}})
    assert result.status_code==200,result.text;job=result.json()
    assert s.job_update(job['id'],status='running');second=register(job,tmp_path/'timbre.wav')
    assert s.job_update(job['id'],status='succeeded',result={'assets':[second]})
    result=team['a'].post(candidate(team,job)+'/adopt',json=version(card));assert result.status_code==200,result.text
    card=result.json()['target'];content=deepcopy(card['content']);voice=content['voice_profile']
    voice.update(status='locked',referenceAssetId=second['id'],referenceVersion=2)
    voice['lockedVersions']['2']=voice_snapshot(voice)
    result=save(team,card,content);assert result.status_code==200,result.text
    return result.json(),first,second


def state(team,selection=None,key='state'):
    content={'card':{'id':key,'kind':'character_state','name':key,'parentCardId':'hero','currentVersionId':key+'-v1','status':'active'},
        'versions':{key+'-v1':{'id':key+'-v1','cardId':key,'version':1,'parentVersionId':'hero-v1','status':'draft',
            'spec':{'description':'black robe','attributes':[]},'invariants':[],'references':[]}},'voice_profile':None}
    if selection is not None:content['card']['voiceVersion']=selection
    result=team['b'].post(url(team),json={'kind':'visual_card','content':content})
    assert result.status_code==201,result.text
    return result.json()


def select_default(team,card,value):
    content=deepcopy(card['content']);content['voice_profile']['defaultVersion']=value
    result=save(team,card,content);assert result.status_code==200,result.text
    return result.json()


def test_library_preserves_old_default_and_state_pins_version_in_video_preview_single_batch(team,tmp_path,monkeypatch):
    card,first,second=library(team,tmp_path);state_row=state(team,2)
    model,shot=sample_shot(team,monkeypatch)
    content=deepcopy(shot['content']);content['shot']['dialogues'][0]['characterCardId']='state'
    result=save(team,shot,content);assert result.status_code==200,result.text;shot=result.json()
    path='/api/projects/'+team['pid']
    preview=team['a'].post(path+'/video-spec',json={'node_id':'sample-node','model_id':model})
    assert preview.status_code==200,preview.text
    samples=preview.json()['voice_samples']
    assert [(x['voiceCardId'],x['voiceVersion'],x['assetId']) for x in samples]==[('state',2,second['id']),('hero',1,first['id'])]
    for batch in (False,True):
        job=submit_sample(team,model,batch)
        assert job['input']['voice_samples']==samples
        assert {card['id'],state_row['id']}<={ref['id'] for ref in job['collaboration']['references']}
    card=select_default(team,card,2)
    latest=team['a'].post(path+'/video-spec',json={'node_id':'sample-node','model_id':model}).json()['voice_samples']
    assert [x['voiceVersion'] for x in latest]==[2,2] and [x['index'] for x in latest]==[1,1]
    assert team['b'].get(url(team,state_row)).json()==state_row


@pytest.mark.parametrize('tamper',['history','remove','default','current'])
def test_locked_library_cannot_be_forged_overwritten_or_erased(team,tmp_path,tamper):
    card,_,_=library(team,tmp_path);content=deepcopy(card['content']);profile=content['voice_profile']
    if tamper=='history':profile['lockedVersions']['1']['voiceType']='forged'
    if tamper=='remove':profile['lockedVersions'].pop('1')
    if tamper=='default':profile['defaultVersion']=999
    if tamper=='current':profile['previewText']='overwrite locked current'
    response=save(team,card,content);assert response.status_code==422,response.text
    assert team['a'].get(url(team,card)).json()==card


def test_state_selection_uses_state_owner_not_parent_owner_and_can_return_to_inheritance(team,tmp_path):
    card,_,_=library(team,tmp_path);row=state(team)
    content=deepcopy(row['content']);content['card']['voiceVersion']=2
    assert save(team,row,content).status_code==403
    response=save(team,row,content,client=team['b']);assert response.status_code==200,response.text;row=response.json()
    assert team['a'].get(url(team,card)).json()==card
    content['card']['voiceVersion']=999
    assert save(team,row,content,client=team['b']).status_code==422
    content['card'].pop('voiceVersion')
    response=save(team,row,content,client=team['b']);assert response.status_code==200,response.text
    document=team['a'].get('/api/projects/'+team['pid']).json()['document']
    cid,profile=resolved_voice(document,{}, {'characterCardId':'state'})
    assert cid=='hero' and profile['version']==1


def test_state_dialogue_freezes_parent_and_state_rejects_forged_voice_and_late_selection(team,tmp_path):
    card,_,_=library(team,tmp_path);state_row=state(team,2)
    shot=create(team,dialogues=[{'id':'state-line','characterCardId':'state','text':'state words'}])
    body={'node_id':'dialogue:state-line','kind':'audio','submission_id':uuid.uuid4().hex,
        'input':{'model_id':card['content']['voice_profile']['model_id'],'voice_type':'test-voice','prompt':'state words',
            'dialogue':{'id':'state-line','shotUid':shot['content']['shot']['uid'],'characterCardId':'state','voiceCardId':'state','voiceVersion':2,'text':'state words'}}}
    bad=deepcopy(body);bad['input']['dialogue']['voiceCardId']='hero'
    path='/api/projects/'+team['pid']+'/jobs';before=team['a'].get(path).json()
    assert team['a'].post(path,json=bad).status_code==409
    assert team['a'].get(path).json()==before
    result=team['a'].post(path,json=body);assert result.status_code==200,result.text
    job=result.json();assert {card['id'],state_row['id']}<={ref['id'] for ref in job['collaboration']['references']}
    audio_result(job,tmp_path)
    content=deepcopy(state_row['content']);content['card']['voiceVersion']=1
    result=save(team,state_row,content,client=team['b']);assert result.status_code==200,result.text
    assert team['a'].post(candidate(team,job)+'/adopt',json={**version(shot),'accept_stale':True}).status_code==409


def test_resolver_inherits_and_rejects_ambiguous_implicit_states():
    document={'filmBible':{'visual':{'cards':{'hero':{'id':'hero','kind':'character'},
        'one':{'id':'one','kind':'character_state','parentCardId':'hero','voiceVersion':1},
        'two':{'id':'two','kind':'character_state','parentCardId':'hero','voiceVersion':2}},
        'versions':{'one-v':{'cardId':'one'},'two-v':{'cardId':'two'}}},'voices':{'profiles':{
        'hero':{'version':2,'status':'locked','defaultVersion':1,'lockedVersions':{'1':{'version':1,'status':'locked'}}}}}}}
    shot={'assetBindings':{'characters':[{'versionId':'one-v'},{'versionId':'two-v'}]}}
    with pytest.raises(ValueError,match='多个'):resolved_voice(document,shot,{'characterCardId':'hero'})
    assert resolved_voice(document,shot,{'characterCardId':'one'})[1]['version']==1


def test_default_changes_only_invalidate_inheritors_across_episodes_and_drafts_keep_live_voice(team,tmp_path,monkeypatch):
    card,_,_=library(team,tmp_path);state_row=state(team,2);_,root=sample_shot(team,monkeypatch)
    episode=team['admin'].post(f"/api/productions/{team['production']}/episodes",json={'title':'Second'}).json()
    other={**team,'pid':episode['id']};content=deepcopy(root['content'])
    for line in content['shot']['dialogues']:line['characterCardId']='state'
    result=team['b'].post(url(other),json={'kind':'shot','content':content});assert result.status_code==201,result.text
    pinned=result.json();card=select_default(team,card,2)
    changed=team['a'].get(url(team,root)).json()
    assert changed['content']['nodes'][0]['data']['generation_revision']==1
    assert team['b'].get(url(other,pinned)).json()==pinned
    content=deepcopy(card['content']);profile=content['voice_profile'];profile.update(version=3,status='draft')
    for key in ('previewAssetId','generationJobId','referenceAssetId','referenceVersion'):profile.pop(key,None)
    result=save(team,card,content);assert result.status_code==200,result.text
    assert team['a'].get(url(team,root)).json()==changed
    assert team['b'].get(url(other,pinned)).json()==pinned
    state_content=deepcopy(state_row['content']);state_content['card']['voiceVersion']=1
    result=save(team,state_row,state_content,client=team['b']);assert result.status_code==200,result.text
    assert team['a'].get(url(team,root)).json()==changed
    latest=team['b'].get(url(other,pinned)).json()
    assert latest['content']['nodes'][0]['data']['generation_revision']==1
    assert latest['assignee_id']==pinned['assignee_id'] and latest['assignment_epoch']==pinned['assignment_epoch']
    assert save(other,pinned,pinned['content'],client=team['b']).status_code==409


def test_current_state_dialogue_can_be_adopted_and_used_in_full_dialogue_video(team,tmp_path,monkeypatch):
    card,_,_=library(team,tmp_path);state(team,2);model,shot=sample_shot(team,monkeypatch)
    content=deepcopy(shot['content']);content['shot']['dialogueMode']='full_dialogue'
    content['shot']['dialogues']=[{'id':'state-line','characterCardId':'state','text':'state words'}]
    result=save(team,shot,content);assert result.status_code==200,result.text;shot=result.json()
    result=team['a'].post('/api/projects/'+team['pid']+'/jobs',json={'node_id':'dialogue:state-line','kind':'audio','submission_id':uuid.uuid4().hex,
        'input':{'model_id':card['content']['voice_profile']['model_id'],'voice_type':'test-voice','prompt':'state words',
            'dialogue':{'id':'state-line','shotUid':'sample-shot','characterCardId':'state','voiceCardId':'state','voiceVersion':2,'text':'state words'}}})
    assert result.status_code==200,result.text;job=result.json();asset=audio_result(job,tmp_path)
    result=team['a'].post(candidate(team,job)+'/adopt',json=version(shot));assert result.status_code==200,result.text
    video=submit_sample(team,model)
    assert video['input']['dialogue_audio'][0]['assetId']==asset['id']
    assert video['input']['dialogue_audio'][0]['voiceVersion']==2 and not video['input'].get('voice_samples')
