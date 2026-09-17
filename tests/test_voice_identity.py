"""Voice-sample prerequisite: current preview identity, real PG, no paid API."""
from copy import deepcopy
import uuid
import pytest
from tests.test_p5_object_transactions import team,admin,clients,clear_auth_rate_limits,url,version,save
from tests.test_p5_object_candidates import audio_model,voice_card,audio_result,candidate

def preview(team,model):
    response=team['a'].post('/api/projects/'+team['pid']+'/jobs',json={
        'node_id':'voice-profile:hero','kind':'audio','submission_id':uuid.uuid4().hex,
        'input':{'model_id':model,'prompt':'preview words','voice_type':'test-voice',
                 'voice_profile':{'cardId':'hero','version':1,'identity':'caller-forged'}}})
    assert response.status_code==200,response.text
    return response.json()

@pytest.mark.parametrize('patch',[{'previewText':'different words'},{'parameters':{'speechRate':10,'emotion':''}},
                                 {'parameters':{'speechRate':0,'emotion':'happy'}}])
def test_late_preview_cannot_adopt_into_changed_identity_even_with_accept_stale(team,tmp_path,patch):
    model=audio_model(team);card=voice_card(team,model);job=preview(team,model);audio_result(job,tmp_path)
    content=deepcopy(card['content']);content['voice_profile'].update(patch)
    response=save(team,card,content)
    assert response.status_code==200,response.text
    current=response.json()
    response=team['a'].post(candidate(team,job)+'/adopt',json={**version(current),'accept_stale':True})
    assert response.status_code==409,response.text
    assert team['a'].get(url(team,card)).json()==current


def test_same_voice_after_cosmetic_card_edit_can_adopt_and_lock_but_changed_text_cannot(team,tmp_path):
    model=audio_model(team);card=voice_card(team,model);job=preview(team,model);asset=audio_result(job,tmp_path)
    content=deepcopy(card['content']);content['card']['name']='Cosmetic rename'
    current=save(team,card,content).json()
    response=team['a'].post(candidate(team,job)+'/adopt',json={**version(current),'accept_stale':True})
    assert response.status_code==200,response.text
    current=response.json()['target'];content=deepcopy(current['content'])
    content['voice_profile']['previewText']='different words'
    changed=save(team,current,content);assert changed.status_code==200,changed.text
    changed=changed.json();content['voice_profile']['status']='locked'
    response=save(team,changed,content);assert response.status_code==409,response.text
    content=deepcopy(current['content']);content['voice_profile']['status']='locked'
    response=save(team,changed,content);assert response.status_code==200,response.text
    assert response.json()['content']['voice_profile']['previewAssetId']==asset['id']


def test_provider_parameters_cannot_differ_from_saved_audition(team):
    from tests.platform_model_helpers import publish_test_model
    model=uuid.uuid4().hex
    publish_test_model(team['admin'],model,kind='audio',provider_type='volcengine_speech',
        rules={'voice_type':{'type':'string','enum':['test-voice']},'speech_rate':{'type':'integer','min':-50,'max':100},'emotion':{'type':'string'}},
        defaults={'voice_type':'test-voice','speech_rate':0,'emotion':''})
    voice_card(team,model)
    path='/api/projects/'+team['pid']+'/jobs'
    before=team['a'].get(path).json()
    for parameters in ({'speech_rate':10},{'emotion':'happy'}):
        response=team['a'].post(path,json={'node_id':'voice-profile:hero','kind':'audio','submission_id':uuid.uuid4().hex,
            'input':{'model_id':model,'prompt':'preview words','voice_type':'test-voice','parameters':parameters,
                     'voice_profile':{'cardId':'hero','version':1}}})
        assert response.status_code==422,response.text
    assert team['a'].get(path).json()==before


def test_voice_submission_retry_keeps_original_fingerprint_and_no_duplicate(team):
    model=audio_model(team);voice_card(team,model);job=preview(team,model)
    response=team['a'].post('/api/projects/'+team['pid']+'/jobs',json={
        'node_id':job['node_id'],'kind':'audio','submission_id':job['submission_id'],
        'input':{'model_id':model,'prompt':'preview words','voice_type':'test-voice',
                 'voice_profile':{'cardId':'hero','version':1,'identity':'caller-forged'}}})
    assert response.status_code==200,response.text
    assert response.json()['id']==job['id'] and response.json()['input_hash']==job['input_hash']
