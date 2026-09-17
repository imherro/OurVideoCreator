"""Confirmed timbre references: real PostgreSQL/media, mocked commercial transport."""
from copy import deepcopy
import json
import uuid
import wave
import httpx
import pytest
from backend import store as s
from backend.providers.common import register
from backend.voice_samples import compile_samples, submission_assets
from backend.worker import Worker
from tests.test_p5_object_transactions import team, admin, clients, clear_auth_rate_limits, url, version, save
from tests.test_p5_object_candidates import audio_model, voice_card, candidate
from tests.test_voice_identity import preview
from tests.platform_model_helpers import publish_test_model
from tests.egress_helpers import public_test_dns, mock_egress


def confirmed_voice(team,tmp_path,confirm=True,seconds=3):
    model=audio_model(team);card=voice_card(team,model);job=preview(team,model)
    path=tmp_path/'timbre.wav'
    with wave.open(str(path),'wb') as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(8000)
        out.writeframes(b'\0\0'*int(8000*seconds))
    assert s.job_update(job['id'],status='running')
    asset=register(job,path)
    assert s.job_update(job['id'],status='succeeded',result={'assets':[asset]})
    result=team['a'].post(candidate(team,job)+'/adopt',json=version(card))
    assert result.status_code==200,result.text
    card=result.json()['target'];content=deepcopy(card['content'])
    content['voice_profile']['status']='locked'
    if confirm:content['voice_profile'].update(referenceAssetId=asset['id'],referenceVersion=1)
    result=save(team,card,content);assert result.status_code==200,result.text
    return result.json(),asset


def sample_shot(team,monkeypatch,kind='hc_atom',model_name=None):
    public_test_dns(monkeypatch)
    names={'hc_atom':'doubao-seedance-2.5','volcengine_ark':'doubao-seedance-2-5-260628',
           'runninghub':'bytedance/seedance-2.5-token'}
    model=uuid.uuid4().hex
    from backend.motion_references import protocol_limits
    selected=model_name or names[kind];limits=protocol_limits(kind,selected)
    publish_test_model(team['admin'],model,kind='video',provider_type=kind,upstream_model=selected,
        url='https://provider.example',options={'public_base_url':'https://studio.example'},
        capabilities={'multimodal_reference':True,'audio_reference':True,'voice_sample_reference':True,'audio_only_reference':limits['audio_only'],'video_reference':True},
        rules={'duration':{'type':'integer','min':4,'max':limits['max_duration']},'ratio':{'type':'string','enum':['16:9']},'generate_audio':{'type':'boolean'}},
        defaults={'duration':4,'ratio':'16:9','generate_audio':False})
    content={'shot':{'id':'sample-shot','uid':'sample-shot','videoNode':'sample-node','duration':4,
        'videoReferenceMode':'multimodal','dialogueMode':'voice_sample',
        'dialogues':[{'id':'line1','characterCardId':'hero','characterName':'Hero','text':'Actual dialogue','emotion':'happy'},
                     {'id':'line2','characterCardId':'hero','characterName':'Hero','text':'Second line'}]},
        'nodes':[{'id':'sample-node','type':'media','data':{'kind':'video','model_id':model,'prompt':'人物走动'}}]}
    result=team['a'].post(url(team),json={'kind':'shot','content':content})
    assert result.status_code==201,result.text
    return model,result.json()


def submit_sample(team,model,batch=False):
    path='/api/projects/'+team['pid']
    if batch:
        result=team['a'].post(path+'/run',json={'submission_id':uuid.uuid4().hex,'node_ids':['sample-node'],'exact':True})
        assert result.status_code==200,result.text
        return team['a'].get('/api/jobs/'+result.json()['job_ids'][0]).json()
    result=team['a'].post(path+'/jobs',json={'node_id':'sample-node','kind':'video','submission_id':uuid.uuid4().hex,
        'input':{'model_id':model,'prompt':'人物走动','voice_samples':[{'assetId':'forged'}],'dialogue_audio':[{'asset_id':'forged'}]}})
    assert result.status_code==200,result.text
    return result.json()


@pytest.mark.parametrize('batch',[False,True])
def test_preview_single_batch_share_confirmed_sample_without_timing_extension(team,monkeypatch,tmp_path,batch):
    card,asset=confirmed_voice(team,tmp_path,seconds=8)
    model,shot=sample_shot(team,monkeypatch);path='/api/projects/'+team['pid']
    before=[team['a'].get(path+suffix).json() for suffix in ('','/assets','/jobs')]
    result=team['viewer'].post(path+'/video-spec',json={'node_id':'sample-node','model_id':model})
    assert result.status_code==200,result.text
    spec=result.json()
    assert [team['a'].get(path+suffix).json() for suffix in ('','/assets','/jobs')]==before
    job=submit_sample(team,model,batch)
    for key in ('voice_samples','dialogue_mode','reference_manifest','prompt','parameters'):
        assert job['input'][key]==spec[key],key
    samples=spec['voice_samples'];assert len(samples)==1 and samples[0]['assetId']==asset['id']
    assert samples[0]['media']['duration']==8 and samples[0]['purpose']=='timbre_only'
    assert spec['parameters']['duration']==4 and spec['parameters']['generate_audio'] is True
    assert not job['input'].get('dialogue_audio') and not job['input'].get('dialogue_audio_asset_ids')
    assert 'Actual dialogue' in spec['prompt'] and 'preview words' not in spec['prompt']
    assert '不复述或播放样本台词' in spec['prompt']


def test_old_locked_audition_needs_explicit_confirmation_and_cannot_change_identity(team,monkeypatch,tmp_path):
    card,asset=confirmed_voice(team,tmp_path,confirm=False);model,_=sample_shot(team,monkeypatch)
    path='/api/projects/'+team['pid']+'/video-spec'
    payload={'node_id':'sample-node','model_id':model}
    rejected=team['a'].post(path,json=payload)
    assert rejected.status_code==400 and '尚未确认' in rejected.text,rejected.text
    content=deepcopy(card['content']);content['voice_profile'].update(referenceAssetId=asset['id'],referenceVersion=1)
    forged=deepcopy(content);forged['voice_profile']['previewText']='changed'
    assert save(team,card,forged).status_code in (409,422)
    assert save(team,card,content,client=team['b']).status_code==403
    result=save(team,card,content);assert result.status_code==200,result.text
    assert team['a'].post(path,json=payload).status_code==200


@pytest.mark.parametrize('kind,model_name',[('hc_atom',None),('volcengine_ark',None),('runninghub',None),
    ('hc_atom','dreamina-seedance-2.0'),('volcengine_ark','doubao-seedance-2-0-260128')])
def test_worker_sends_timbre_not_fixed_dialogue_and_resume_never_reuploads(team,monkeypatch,tmp_path,kind,model_name):
    confirmed_voice(team,tmp_path);model,shot=sample_shot(team,monkeypatch,kind,model_name)
    if model_name:
        # The 2.0 protocol rejects audio-only; add an actual fixture-owned MP4 reference.
        rejected=team['a'].post('/api/projects/'+team['pid']+'/video-spec',json={'node_id':'sample-node','model_id':model})
        assert rejected.status_code==400 and '仅音频' in rejected.text,rejected.text
        from tests.test_motion_references import media as media_fixture
        media_path=media_fixture.__wrapped__(tmp_path)
        with media_path.open('rb') as stream:
            result=team['a'].post('/api/projects/'+team['pid']+'/assets',files={'file':('motion.mp4',stream,'video/mp4')})
        assert result.status_code==200,result.text
        content=deepcopy(shot['content']);content['shot']['motionReference']={'assetId':result.json()['id'],'cameraMode':'use_shot_camera'}
        result=save(team,shot,content);assert result.status_code==200,result.text
    job=submit_sample(team,model)
    requests=[]
    def handle(request):
        path=request.url.path;requests.append(path)
        if path.endswith('/media/upload/binary'):
            assert b'audio' in request.content
            return httpx.Response(200,json={'code':0,'data':{'download_url':'https://media.example/timbre.wav'}})
        if path.endswith('/query') or request.method=='GET':
            return httpx.Response(200,json={'status':'FAILED','errorMessage':'mock-terminal','error':'mock-terminal'})
        body=json.loads(request.content)
        if kind=='runninghub':
            assert body['audioUrls']==['https://media.example/timbre.wav'] and body['generateAudio'] is True
        else:
            audios=[item for item in body['content'] if item.get('role')=='reference_audio']
            assert len(audios)==1 and body['generate_audio'] is True
            expected='data:audio/wav;base64,' if kind=='volcengine_ark' else 'https://studio.example/api/provider-assets/'
            assert audios[0]['audio_url']['url'].startswith(expected)
            if model_name:assert 'omni_reference_task_type' not in body
        return httpx.Response(200,json={'id':'sample-remote','taskId':'sample-remote'})
    mock_egress(monkeypatch,handle)
    from tests.test_hc_atom import NoWait
    worker=Worker();worker.halt=NoWait();assert s.job_update(job['id'],status='running')
    with pytest.raises(ValueError,match='mock-terminal'):worker.execute(job)
    with s.db() as c:resumed=s.unpack(c.execute('SELECT * FROM jobs WHERE id=%s',(job['id'],)).fetchone())
    requests.clear()
    with pytest.raises(ValueError,match='mock-terminal'):worker.execute(resumed)
    assert len(requests)==1 and ('sample-remote' in requests[0] or requests[0].endswith('/query'))


def test_samples_dedupe_media_keep_role_mapping_validate_limits_and_source_hash(team,tmp_path):
    card,asset=confirmed_voice(team,tmp_path)
    profile=card['content']['voice_profile']
    document={'filmBible':{'voices':{'profiles':{'hero':profile,'other':profile}}}}
    shot={'dialogues':[{'characterCardId':cid,'text':'line','characterName':cid} for cid in ['hero','other','hero']]}
    caps={'max_audio':1,'max_reference_duration':15}
    samples=compile_samples(document,shot,team['pid'],caps)
    assert [item['characterCardId'] for item in samples]==['hero','other']
    assert [item['index'] for item in samples]==[1,1]
    with pytest.raises(ValueError,match='数量'):compile_samples(document,shot,team['pid'],{**caps,'max_audio':0})
    with pytest.raises(ValueError,match='纯音频'):compile_samples(document,shot,team['pid'],{**caps,'max_reference_duration':2})
    job={'project_id':team['pid'],'input':{'voice_samples':samples}}
    sources=submission_assets(job);assert len(sources)==1
    # Tamper only this fixture-owned temporary result, never user media.
    with (s.ASSETS/sources[0]['path']).open('ab') as out:out.write(b'changed')
    with pytest.raises(ValueError,match='提交后变化'):submission_assets(job)


@pytest.mark.parametrize('caps',[
    {'voice_sample_reference':True},
    {'multimodal_reference':True,'voice_sample_reference':True},
    {'multimodal_reference':True,'audio_reference':True,'voice_sample_reference':True,'max_audio_references':11},
])
def test_invalid_published_sample_contract_rejected(caps):
    from backend.model_validation import model_definition
    with pytest.raises(ValueError):
        model_definition({'name':'test','upstream_model':'doubao-seedance-2.5','capabilities':caps},{'type':'hc_atom'},'video')


@pytest.mark.parametrize('trashed',[False,True])
def test_shared_voice_confirmation_invalidates_other_episode_without_cross_episode_write_permission(team,monkeypatch,tmp_path,trashed):
    card,asset=confirmed_voice(team,tmp_path,confirm=False)
    _,root=sample_shot(team,monkeypatch)
    episode=team['admin'].post(f"/api/productions/{team['production']}/episodes",json={'title':'Second'}).json()
    other={**team,'pid':episode['id']}
    # Deliberately reuse EP-local node IDs. The graph namespaces must stay separate.
    content=deepcopy(root['content']);content['nodes'][0]['data']['prompt']='Other editor draft'
    result=team['b'].post(url(other),json={'kind':'shot','content':content})
    assert result.status_code==201,result.text
    second=result.json()
    from tests.test_p5_canonical_integration import node
    unrelated=node(other,team['b'],'unrelated-voice-node')
    if trashed:assert team['admin'].delete('/api/projects/'+other['pid']).status_code==200
    changed=deepcopy(card['content']);changed['voice_profile'].update(referenceAssetId=asset['id'],referenceVersion=1)
    result=save(team,card,changed);assert result.status_code==200,result.text
    if trashed:assert team['admin'].post('/api/trash/project/'+other['pid']+'/restore').status_code==200
    latest=team['b'].get(url(other,second)).json()
    assert latest['content']['nodes'][0]['data']['prompt']=='Other editor draft'
    assert latest['content']['nodes'][0]['data']['generation_revision']==1
    assert latest['assignee_id']==second['assignee_id']==team['bid']
    if not trashed:
        assert latest['assignment_epoch']==second['assignment_epoch'] and latest['revision']==second['revision']+1
    assert save(other,second,second['content'],client=team['b']).status_code==409
    assert save(team,latest,latest['content'],client=team['b']).status_code==404
    unchanged=team['b'].get(url(other,unrelated)).json()
    assert unchanged['content']==unrelated['content']
    assert team['a'].get(url(team,root)).json()['content']['nodes'][0]['data']['generation_revision']==1


def test_default_dialogue_mode_invalidates_inherited_shot_only_and_rejects_viewer(team,monkeypatch):
    _,shot=sample_shot(team,monkeypatch);path='/api/projects/'+team['pid']
    project=team['admin'].get(path).json()
    payload={'expected_revision':project['revision'],'patch':{'dialogueMode':'voice_sample'}}
    assert team['viewer'].patch(path+'/metadata',json=payload).status_code==403
    result=team['admin'].patch(path+'/metadata',json=payload);assert result.status_code==200,result.text
    assert team['a'].get(url(team,shot)).json()==shot
    content=deepcopy(shot['content']);content['shot']['dialogueMode']=''
    result=save(team,shot,content);assert result.status_code==200,result.text
    inherited=result.json();project=team['admin'].get(path).json()
    result=team['admin'].patch(path+'/metadata',json={'expected_revision':project['revision'],'patch':{'dialogueMode':'full_dialogue'}})
    assert result.status_code==200,result.text
    latest=team['a'].get(url(team,shot)).json()
    assert latest['revision']==inherited['revision']+1
    assert latest['content']['nodes'][0]['data']['generation_revision']==2


def test_empty_sample_mode_strips_forged_fixed_dialogue_without_changing_legacy_mode():
    from backend.motion_references import compile_motion_input
    value=compile_motion_input({'dialogueMode':'voice_sample'},'empty','video',
        {'dialogue_audio':[{'asset_id':'forged'}],'audio_asset_ids':['forged'],'voice_samples':[{'assetId':'forged'}]},'unused',None)
    assert not value.get('dialogue_audio') and not value.get('voice_samples') and not value.get('audio_asset_ids')


def test_sample_asset_protection_total_duration_and_real_decode(team,tmp_path,monkeypatch):
    card,asset=confirmed_voice(team,tmp_path,seconds=8)
    result=team['admin'].delete('/api/projects/'+team['pid']+'/assets/'+asset['id'])
    assert result.status_code==409,result.text  # Existing reference protection recognizes the new field.
    profile=card['content']['voice_profile'];doc={'filmBible':{'voices':{'profiles':{'hero':profile}}}}
    shot={'dialogues':[{'characterCardId':'hero','text':'actual'}]};caps={'max_audio':3,'max_reference_duration':15}
    other=team['admin'].post('/api/projects',json={'name':'Other isolated work'}).json()
    with pytest.raises(ValueError,match='丢失'):compile_samples(doc,shot,other['id'],caps)
    audio_job=team['a'].get('/api/jobs/'+profile['generationJobId']).json()
    second=register(audio_job,tmp_path/'timbre.wav')
    doc['filmBible']['voices']['profiles']['other']={**profile,'referenceAssetId':second['id']}
    shot['dialogues'].append({'characterCardId':'other','text':'another'})
    with pytest.raises(ValueError,match='总时长'):compile_samples(doc,shot,team['pid'],caps)
    # Even plausible duration metadata cannot make a broken sample decodable.
    from backend.providers.common import assets_by_ids
    source=assets_by_ids(audio_job,[asset['id']])[0]
    (s.ASSETS/source['path']).write_bytes(b'not a WAV container')
    monkeypatch.setattr('backend.voice_samples.probe',lambda path:{'has_audio':True,'duration':8})
    with pytest.raises(ValueError,match='无法完整解码'):compile_samples(doc,shot,team['pid'],caps)
