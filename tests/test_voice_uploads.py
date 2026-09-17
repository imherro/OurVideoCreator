"""Real local media and PostgreSQL; upload is not TTS registration or adoption."""
from copy import deepcopy
import io
import uuid
import wave
import pytest
from backend import store as s
from backend.voice_resolution import voice_snapshot
from backend.voice_reference_uploads import validate_file
from tests.test_p5_object_transactions import team,admin,clients,clear_auth_rate_limits,url,version,save,create
from tests.test_p5_object_candidates import voice_card,audio_model,audio_result,candidate
from tests.test_voice_samples import sample_shot,submit_sample
from tests.test_voice_identity import preview
from tests.test_voice_library import state


def wav(seconds=3):
    data=io.BytesIO()
    with wave.open(data,'wb') as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(8000);out.writeframes(b'\0\0'*int(8000*seconds))
    return data.getvalue()


def upload(team,*,seconds=3,special=True):
    result=team['a'].post('/api/projects/'+team['pid']+'/assets?category=voice'+('&voice_reference=true' if special else ''),
        files={'file':('sample.wav',wav(seconds),'audio/wav')})
    assert result.status_code==200,result.text
    return result.json()


def admit(team,asset,**kwargs):
    return team['a'].post('/api/projects/'+team['pid']+'/assets/'+asset['id']+'/voice-reference',json={'authorized':True},**kwargs)


def profile(asset,version=1):
    return {'cardId':'hero','version':version,'status':'draft','name':'上传男声','description':'测试合成音，不是真人声音',
        'model_id':'','voiceType':'','previewText':'','parameters':{'speechRate':0,'emotion':''},
        'source':{'type':'uploaded','originalAssetId':asset['id'],'authorizedAt':asset['metadata']['voice_reference']['authorized_at']},
        'previewAssetId':asset['id'],'lockedVersions':{}}


def setup_voice(team):
    card=voice_card(team,'');asset=upload(team);result=admit(team,asset);assert result.status_code==200,result.text;asset=result.json()
    content=deepcopy(card['content']);content['voice_profile']=profile(asset,2)
    result=save(team,card,content);assert result.status_code==200,result.text
    return result.json(),asset


def lock(team,card):
    content=deepcopy(card['content']);voice=content['voice_profile']
    voice.update(status='locked',referenceAssetId=voice['previewAssetId'],referenceVersion=voice['version'],defaultVersion=voice['version'])
    voice['lockedVersions'][str(voice['version'])]=voice_snapshot(voice)
    result=save(team,card,content);assert result.status_code==200,result.text
    return result.json()


def test_upload_and_existing_asset_admission_no_tts_configuration_no_implicit_card_write(team):
    card=voice_card(team,'');asset=upload(team,special=False);path='/api/projects/'+team['pid']
    before=team['a'].get(path+'/jobs').json()
    endpoint=path+'/assets/'+asset['id']+'/voice-reference'
    assert team['a'].post(endpoint,json={'authorized':False}).status_code==400
    assert team['a'].post(endpoint,json={'authorized':'yes'}).status_code==422
    assert team['viewer'].post(endpoint,json={'authorized':True}).status_code==403
    result=admit(team,asset);assert result.status_code==200,result.text;asset=result.json()
    receipt=asset['metadata']['voice_reference'];assert receipt['declared_by']==team['aid'] and receipt['declaration']=='user_declared'
    assert admit(team,asset).json()['metadata']['voice_reference']==receipt
    assert team['a'].get(url(team,card)).json()==card and team['a'].get(path+'/jobs').json()==before
    content=deepcopy(card['content']);content['voice_profile']=profile(asset,2)
    assert save(team,card,content,client=team['b']).status_code==403
    result=save(team,card,content);assert result.status_code==200,result.text;card=result.json()
    assert card['content']['voice_profile']['status']=='draft' and not card['content']['voice_profile'].get('referenceAssetId')
    card=lock(team,card);assert team['a'].get(url(team,card)).json()==card
    assert team['admin'].delete(path+'/assets/'+asset['id']).status_code==409


def test_upload_samples_share_preview_single_batch_and_cross_episode_state_without_audio_jobs(team,monkeypatch):
    card,asset=setup_voice(team);card=lock(team,card);state_row=state(team,2)
    episode=team['admin'].post(f"/api/productions/{team['production']}/episodes",json={'title':'Shared voice'}).json()
    other={**team,'pid':episode['id']};model,shot=sample_shot(other,monkeypatch)
    content=deepcopy(shot['content'])
    for line in content['shot']['dialogues']:line['characterCardId']='state'
    result=save(other,shot,content);assert result.status_code==200,result.text
    path='/api/projects/'+other['pid'];snapshot=team['a'].get(path).json()
    spec=team['viewer'].post(path+'/video-spec',json={'node_id':'sample-node','model_id':model})
    assert spec.status_code==200,spec.text;spec=spec.json()
    sample=spec['voice_samples'][0]
    assert sample['assetId']==asset['id'] and sample['source']=='uploaded' and sample['voiceCardId']=='state'
    assert sample['media']['duration']==3 and spec['shot_duration']==4
    for batch in (False,True):
        job=submit_sample(other,model,batch)
        assert job['input']['voice_samples']==spec['voice_samples'] and not job['input'].get('dialogue_audio')
        assert {card['id'],state_row['id']}<={ref['id'] for ref in job['collaboration']['references']}
    assert all(job['kind']=='video' for job in team['a'].get(path+'/jobs').json())
    assert team['a'].get(path).json()==snapshot


def test_uploaded_voice_rejects_tts_single_batch_and_full_dialogue_without_jobs(team,monkeypatch):
    card,_=setup_voice(team);card=lock(team,card);state(team,2);model,shot=sample_shot(team,monkeypatch)
    path='/api/projects/'+team['pid'];content=deepcopy(shot['content']);content['shot']['dialogueMode']='full_dialogue'
    for line in content['shot']['dialogues']:line['characterCardId']='state'
    result=save(team,shot,content);assert result.status_code==200,result.text
    result=team['a'].post(path+'/video-spec',json={'node_id':'sample-node','model_id':model})
    assert result.status_code==400 and '上传声音' in result.text,result.text
    body={'node_id':'dialogue:line1','kind':'audio','submission_id':uuid.uuid4().hex,
        'input':{'model_id':'forged','voice_type':'forged','prompt':'Actual dialogue',
            'dialogue':{'id':'line1','shotUid':'sample-shot','characterCardId':'state','voiceCardId':'state','voiceVersion':2,'text':'Actual dialogue'}}}
    for endpoint,payload in [('/jobs',body),('/audio-jobs',{'jobs':[body]})]:
        result=team['a'].post(path+endpoint,json=payload)
        assert result.status_code==400 and '上传声音' in result.text,result.text
    assert team['a'].get(path+'/jobs').json()==[]


def test_switch_to_upload_rejects_late_tts_candidate_even_accept_stale(team,tmp_path):
    model=audio_model(team);card=voice_card(team,model);job=preview(team,model)
    asset=admit(team,upload(team)).json();content=deepcopy(card['content']);content['voice_profile']=profile(asset,2)
    response=save(team,card,content);assert response.status_code==200,response.text;card=response.json()
    audio_result(job,tmp_path)
    result=team['a'].post(candidate(team,job)+'/adopt',json={**version(card),'accept_stale':True})
    assert result.status_code==409,result.text
    assert team['a'].get(url(team,card)).json()==card


def test_upload_requires_real_admission_version_and_immutable_file(team):
    card,asset=setup_voice(team);content=deepcopy(card['content']);voice=content['voice_profile']
    voice['source']['authorizedAt']='forged';assert save(team,card,content).status_code==422
    other=admit(team,upload(team)).json();content=deepcopy(card['content']);content['voice_profile']=profile(other,2)
    assert save(team,card,content).status_code==422
    with s.db() as c:row=c.execute('SELECT path FROM assets WHERE id=%s',(asset['id'],)).fetchone()
    (s.ASSETS/row['path']).write_bytes(wav(4))  # This test owns this isolated fixture media.
    content=deepcopy(card['content']);voice=content['voice_profile'];voice.update(status='locked',referenceAssetId=asset['id'],referenceVersion=2,defaultVersion=2)
    voice['lockedVersions']['2']=voice_snapshot(voice)
    result=save(team,card,content);assert result.status_code==422 and '变化' in result.text,result.text
    assert admit(team,asset).status_code==409
    assert team['a'].get(url(team,card)).json()==card


def test_invalid_upload_no_asset_registration_and_cross_production_admission_denied(team):
    path='/api/projects/'+team['pid']+'/assets';before=team['a'].get(path).json()
    result=team['a'].post(path+'?voice_reference=true',files={'file':('fake.wav',b'not wave','audio/wav')})
    assert result.status_code==400,result.text
    result=team['a'].post(path+'?voice_reference=true',files={'file':('sample.m4a',wav(),'audio/mp4')})
    assert result.status_code==400 and team['a'].get(path).json()==before
    asset=upload(team);other=team['admin'].post('/api/projects',json={'name':'Other work'}).json()
    result=team['admin'].post('/api/projects/'+other['id']+'/assets/'+asset['id']+'/voice-reference',json={'authorized':True})
    assert result.status_code in (400,404),result.text


@pytest.mark.parametrize('seconds',[0,121])
def test_file_duration_and_format_checked_before_admission(tmp_path,seconds):
    path=tmp_path/'sample.wav';path.write_bytes(wav(seconds))
    with pytest.raises(ValueError):validate_file(path)


def test_renamed_container_and_size_rejected(tmp_path):
    path=tmp_path/'renamed.mp3';path.write_bytes(wav())
    with pytest.raises(ValueError):validate_file(path)
    path=tmp_path/'large.wav'
    with path.open('wb') as out:out.truncate(30*1024**2+1)
    with pytest.raises(ValueError,match='30 MB'):validate_file(path)


@pytest.mark.parametrize('kind',['hc_atom','volcengine_ark','runninghub'])
def test_uploaded_worker_uses_existing_media_protocol_and_resume_only_queries(team,tmp_path,monkeypatch,kind):
    from tests import test_voice_samples as samples
    def uploaded_setup(team,tmp_path):
        card,asset=setup_voice(team);return lock(team,card),asset
    monkeypatch.setattr(samples,'confirmed_voice',uploaded_setup)
    samples.test_worker_sends_timbre_not_fixed_dialogue_and_resume_never_reuploads(team,monkeypatch,tmp_path,kind,None)
    jobs=team['a'].get('/api/projects/'+team['pid']+'/jobs').json()
    assert len(jobs)==1 and jobs[0]['kind']=='video' and jobs[0]['input']['voice_samples'][0]['source']=='uploaded'


def test_valid_system_upload_still_respects_stricter_video_model_duration(team,monkeypatch):
    card=voice_card(team,'');asset=admit(team,upload(team,seconds=1)).json()
    content=deepcopy(card['content']);content['voice_profile']=profile(asset,2)
    response=save(team,card,content);assert response.status_code==200,response.text;lock(team,response.json())
    model,_=sample_shot(team,monkeypatch)
    result=team['a'].post('/api/projects/'+team['pid']+'/video-spec',json={'node_id':'sample-node','model_id':model})
    assert result.status_code==400 and '纯音频' in result.text,result.text
    assert team['a'].get('/api/projects/'+team['pid']+'/jobs').json()==[]


def test_admission_rechecks_revoked_membership_after_decode(team,monkeypatch):
    from backend import voice_reference_uploads as uploads
    asset=upload(team)
    def revoke_after_decode(path):
        data=validate_file(path)
        response=team['admin'].delete(f"/api/productions/{team['production']}/members/{team['aid']}")
        assert response.status_code==200,response.text
        return data
    monkeypatch.setattr(uploads,'validate_file',revoke_after_decode)
    result=admit(team,asset);assert result.status_code==404,result.text
    with s.db() as c:metadata=s.unpack(c.execute('SELECT * FROM assets WHERE id=%s',(asset['id'],)).fetchone())['metadata']
    assert 'voice_reference' not in metadata


def test_real_mp3_upload_and_deleted_asset_admission(team,tmp_path):
    import subprocess
    from backend.media import ffmpeg_executable
    source=tmp_path/'source.wav';source.write_bytes(wav());target=tmp_path/'source.mp3'
    subprocess.run([ffmpeg_executable(),'-v','error','-i',str(source),str(target)],check=True,capture_output=True)
    with target.open('rb') as stream:
        result=team['a'].post('/api/projects/'+team['pid']+'/assets?voice_reference=true',files={'file':('sample.mp3',stream,'audio/mpeg')})
    assert result.status_code==200,result.text;asset=result.json()
    assert admit(team,asset).status_code==200
    result=team['admin'].delete('/api/projects/'+team['pid']+'/assets/'+asset['id']);assert result.status_code==200,result.text
    assert admit(team,asset).status_code==404


def test_confirmed_upload_tampered_before_video_submission_rejected(team,monkeypatch):
    card,asset=setup_voice(team);lock(team,card);model,_=sample_shot(team,monkeypatch)
    with s.db() as c:path=c.execute('SELECT path FROM assets WHERE id=%s',(asset['id'],)).fetchone()['path']
    (s.ASSETS/path).write_bytes(wav(4))  # Fixture-only corruption, after lock and before submission.
    result=team['a'].post('/api/projects/'+team['pid']+'/video-spec',json={'node_id':'sample-node','model_id':model})
    assert result.status_code==400 and '已确认文件不一致' in result.text,result.text
    assert team['a'].get('/api/projects/'+team['pid']+'/jobs').json()==[]


def test_upload_cannot_skip_saved_draft_and_jump_directly_to_locked(team):
    card=voice_card(team,'');asset=admit(team,upload(team)).json()
    content=deepcopy(card['content']);voice=profile(asset,2)
    voice.update(status='locked',referenceAssetId=asset['id'],referenceVersion=2,defaultVersion=2)
    voice['lockedVersions']['2']=voice_snapshot(voice);content['voice_profile']=voice
    result=save(team,card,content);assert result.status_code==422 and '先保存上传声音草稿' in result.text,result.text
    assert team['a'].get(url(team,card)).json()==card


@pytest.mark.parametrize('uploaded',[False,True])
def test_sample_replay_preserves_legacy_shape_and_uploaded_source(team,tmp_path,monkeypatch,uploaded):
    if uploaded:
        card,_=setup_voice(team);lock(team,card)
    else:
        from tests.test_voice_samples import confirmed_voice
        confirmed_voice(team,tmp_path)
    model,_=sample_shot(team,monkeypatch);path='/api/projects/'+team['pid']+'/jobs'
    body={'node_id':'sample-node','kind':'video','submission_id':uuid.uuid4().hex,'input':{'model_id':model,'prompt':'人物走动'}}
    response=team['a'].post(path,json=deepcopy(body));assert response.status_code==200,response.text;job=response.json()
    sample=job['input']['voice_samples'][0]
    if uploaded:assert sample['source']=='uploaded'
    else:assert 'source' not in sample  # Legacy TTS defaults keep their existing frozen/hash shape.
    with s.db() as c:original=c.execute('SELECT input,input_hash FROM jobs WHERE id=%s',(job['id'],)).fetchone()
    response=team['a'].post(path,json=deepcopy(body));assert response.status_code==200,response.text
    assert response.json()['id']==job['id']
    with s.db() as c:assert c.execute('SELECT input,input_hash FROM jobs WHERE id=%s',(job['id'],)).fetchone()==original
