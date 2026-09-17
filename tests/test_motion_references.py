"""Reference contracts through real PG and local FFmpeg; commercial sockets blocked."""
import copy
import json
import subprocess
import uuid

import httpx
import pytest

from backend import store as s, model_validation
from backend.media import ffmpeg_executable, probe
from backend.motion_references import compile_motion_input, inspect_motion, silent_motion_asset, protocol_limits
from backend.worker import Worker
from tests.egress_helpers import public_test_dns, mock_egress
from tests.platform_model_helpers import publish_test_model
from tests.test_p5_object_transactions import team, admin, clients, clear_auth_rate_limits, url, version, save


@pytest.fixture
def media(tmp_path):
    path=tmp_path/'motion.mp4'
    run=subprocess.run([ffmpeg_executable(),'-v','error','-f','lavfi','-i','color=c=red:s=720x576:r=24:d=2',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=24000:duration=2','-c:v','libx264','-pix_fmt','yuv420p',
        '-c:a','aac','-shortest',str(path)],capture_output=True,timeout=30)
    assert run.returncode==0,run.stderr
    return path


def setup_motion(team,monkeypatch,media,kind='hc_atom',model_name='doubao-seedance-2.5'):
    public_test_dns(monkeypatch)
    model=uuid.uuid4().hex
    limits=protocol_limits(kind,model_name)
    published=publish_test_model(team['admin'],model,kind='video',provider_type=kind,upstream_model=model_name,
        url='https://provider.example', options={'public_base_url':'https://studio.example'},
        capabilities={'image_reference':True,'max_references':limits['max_images'],'multimodal_reference':True,'video_reference':True},
        rules={'duration':{'type':'integer','min':4,'max':limits['max_duration']},'generate_audio':{'type':'boolean'},
               'ratio':{'type':'string','enum':['16:9','9:16']}},
        defaults={'duration':4,'generate_audio':False,'ratio':'16:9'})
    path='/api/projects/'+team['pid']
    with media.open('rb') as stream:
        uploaded=team['a'].post(path+'/assets?category=reference',files={'file':('motion.mp4',stream,'video/mp4')})
    assert uploaded.status_code==200,uploaded.text
    asset=uploaded.json()
    content={'shot':{'id':'motion-shot','uid':'motion-shot','videoNode':'motion-node','duration':4,
        'videoReferenceMode':'multimodal','motionReference':{'assetId':asset['id'],'cameraMode':'use_shot_camera'}},
        'nodes':[{'id':'motion-node','type':'media','data':{'kind':'video','model_id':model,'prompt':'人物走动'}}]}
    response=team['a'].post(url(team),json={'kind':'shot','content':content})
    assert response.status_code==201,response.text
    return model,response.json(),asset


def submit_motion(team,model,batch=False,**input_fields):
    path='/api/projects/'+team['pid']
    if batch:
        result=team['a'].post(path+'/run',json={'submission_id':uuid.uuid4().hex,'node_ids':['motion-node'],'exact':True})
        assert result.status_code==200,result.text
        return team['a'].get('/api/jobs/'+result.json()['job_ids'][0]).json()
    result=team['a'].post(path+'/jobs',json={'node_id':'motion-node','kind':'video','submission_id':uuid.uuid4().hex,
        'input':{'model_id':model,'prompt':'人物走动','motion_reference':{'assetId':'forged'},**input_fields}})
    assert result.status_code==200,result.text
    return result.json()


@pytest.mark.parametrize('batch',[False,True])
def test_preview_submit_and_silent_derivative_preserve_source(team,monkeypatch,media,batch):
    model,row,asset=setup_motion(team,monkeypatch,media)
    path='/api/projects/'+team['pid']
    before=team['a'].get(path).json()
    before_assets=team['a'].get(path+'/assets').json()
    before_jobs=team['a'].get(path+'/jobs').json()
    response=team['viewer'].post(path+'/video-spec',json={'node_id':'motion-node','model_id':model})
    assert response.status_code==200,response.text
    preview=response.json()
    assert preview['motion_reference']['assetId']==asset['id']
    assert preview['motion_reference']['media']['has_audio'] is True
    assert preview['motion_warnings'] and preview['generation_mode']['requested']=='multimodal'
    assert team['a'].get(path).json()==before
    assert team['a'].get(path+'/assets').json()==before_assets
    assert team['a'].get(path+'/jobs').json()==before_jobs
    job=submit_motion(team,model,batch)
    for key in ('prompt','motion_reference','reference_manifest','generation_mode'):
        assert job['input'][key]==preview[key],key
    assert job['input']['video_spec']['parameters']==preview['parameters']
    assert s.job_update(job['id'],status='running')
    derived=silent_motion_asset(job)
    assert derived['id']!=asset['id'] and derived['source']=='derived'
    assert derived['metadata']['motionDerivedFrom']==asset['id']
    actual=probe(s.ASSETS/derived['path'])
    assert actual['has_audio'] is False and abs(actual['duration']-2)<.1
    from backend.providers.common import assets_by_ids
    original=assets_by_ids(job,[asset['id']])[0]
    assert media.read_bytes()==(s.ASSETS/original['path']).read_bytes()
    assert silent_motion_asset(job)['id']==derived['id']


@pytest.mark.parametrize('kind,model,maximum',[
    ('hc_atom','doubao-seedance-2.5',30),('hc_atom','dreamina-seedance-2.0',15),
    ('volcengine_ark','doubao-seedance-2-5-260628',30),
    ('runninghub','bytedance/seedance-2.5-token',30),
])
def test_published_reference_limits_come_from_private_verified_protocol(kind,model,maximum):
    value=model_validation.model_definition({'name':'Test','upstream_model':model,
        'capabilities':{'multimodal_reference':True,'video_reference':True}}, {'type':kind}, 'video')
    assert value['capabilities']['max_reference_duration']==maximum


@pytest.mark.parametrize('kind,model',[('hc_atom','kling'),('volcengine_ark','unknown-alias'),('video_api','any')])
def test_unimplemented_model_cannot_publish_multimodal(kind,model):
    with pytest.raises(ValueError,match='尚未接通'):
        model_validation.model_definition({'name':'Test','upstream_model':model,
            'capabilities':{'multimodal_reference':True}}, {'type':kind}, 'video')


@pytest.mark.parametrize('kind,model_name',[
    ('hc_atom','dreamina-seedance-2.0'),('volcengine_ark','doubao-seedance-2-0-260128'),
    ('hc_atom','doubao-seedance-2.5'),('volcengine_ark','doubao-seedance-2-5-260628'),
    ('runninghub','bytedance/seedance-2.5-token')])
def test_real_worker_uses_silent_video_and_never_resubmits_handle(team,monkeypatch,media,kind,model_name):
    model,_,asset=setup_motion(team,monkeypatch,media,kind,model_name)
    job=submit_motion(team,model)
    requests=[]
    def handle(request):
        path=request.url.path;requests.append(path)
        if path.endswith('/media/upload/binary'):
            assert b'video/mp4' in request.content
            return httpx.Response(200,json={'code':0,'data':{'download_url':'https://media.example/silent.mp4'}})
        if path.endswith('/query') or request.method=='GET':
            return httpx.Response(200,json={'status':'FAILED','errorMessage':'mock-terminal','error':'mock-terminal'})
        body=json.loads(request.content)
        if kind=='runninghub':
            assert path.endswith('/multimodal-video')
            assert body['videoUrls']==['https://media.example/silent.mp4']
            assert body['omniReferenceTaskType']=='reference'
        else:
            if '2.0' in model_name or '2-0' in model_name:
                assert 'omni_reference_task_type' not in body
            else:
                assert body['omni_reference_task_type']=='reference'
            video=next(item for item in body['content'] if item.get('role')=='reference_video')
            assert video['video_url']['url'].startswith('https://studio.example/api/provider-assets/')
            assert 'signature=' in video['video_url']['url']
        return httpx.Response(200,json={'id':'motion-remote','taskId':'motion-remote'})
    mock_egress(monkeypatch,handle)
    worker=Worker()
    from tests.test_hc_atom import NoWait
    worker.halt=NoWait()
    assert s.job_update(job['id'],status='running')
    with pytest.raises(ValueError,match='mock-terminal'):worker.execute(job)
    with s.db() as c:
        resumed=s.unpack(c.execute('SELECT * FROM jobs WHERE id=%s',(job['id'],)).fetchone())
    requests.clear()
    with pytest.raises(ValueError,match='mock-terminal'):worker.execute(resumed)
    assert len(requests)==1 and ('motion-remote' in requests[0] or requests[0].endswith('/query'))


def test_canonical_reference_changes_invalidate_only_dependents_not_other_owners_content(team,monkeypatch,media):
    from tests.test_p5_canonical_integration import node,graph
    model,root,_=setup_motion(team,monkeypatch,media)
    child=node(team,team['a'],'child');unrelated=node(team,team['b'],'unrelated')
    structure=graph(team)
    assigned=team['admin'].post(url(team,structure,'/assign'),json={**version(structure),'assignee_id':team['aid']})
    assert assigned.status_code==200,assigned.text
    structure=assigned.json();edges=copy.deepcopy(structure['content'])
    edges['edges'].append({'id':'motion-downstream','source':'motion-node','target':'child'})
    assert save(team,structure,edges).status_code==200
    assigned=team['admin'].post(url(team,child,'/assign'),json={**version(child),'assignee_id':team['bid']})
    assert assigned.status_code==200;child=assigned.json()
    original=copy.deepcopy(root['content']);original['shot']['motionReference']['description']='走到门边停下'
    response=save(team,root,original)
    assert response.status_code==200,response.text
    assert response.json()['content']['nodes'][0]['data']['generation_revision']==1
    latest=team['b'].get(url(team,child)).json()
    assert latest['assignee_id']==team['bid'] and latest['assignment_epoch']==child['assignment_epoch']
    assert latest['content']['node']['data']=={'kind':'text','text':'draft','generation_revision':1,'stale':True}
    assert latest['revision']==child['revision']+1
    assert team['b'].get(url(team,unrelated)).json()==unrelated
    assert save(team,child,child['content'],client=team['b']).status_code==409
    assert save(team,latest,latest['content']).status_code==403


def test_changed_reference_late_video_remains_stale_after_explicit_adoption(team,monkeypatch,media):
    from backend.providers.common import register
    from tests.test_p5_object_candidates import candidate
    model,row,_=setup_motion(team,monkeypatch,media)
    job=submit_motion(team,model)
    assert s.job_update(job['id'],status='running')
    asset=register(job,media)
    assert s.job_update(job['id'],status='succeeded',result={'assets':[asset]})
    content=copy.deepcopy(row['content']);content['shot']['motionReference']['cameraMode']='follow_reference'
    response=save(team,row,content);assert response.status_code==200,response.text
    latest=response.json()
    assert team['a'].post(candidate(team,job)+'/adopt',json=version(latest)).status_code==409
    adopted=team['a'].post(candidate(team,job)+'/adopt',json={**version(latest),'accept_stale':True})
    assert adopted.status_code==200,adopted.text
    assert adopted.json()['target']['content']['nodes'][0]['data']['stale'] is True


def test_foreign_reference_and_viewer_write_are_rejected(team,monkeypatch,media):
    model,row,asset=setup_motion(team,monkeypatch,media)
    other=team['admin'].post('/api/projects',json={'name':'Other'}).json()
    with media.open('rb') as stream:
        foreign=team['admin'].post('/api/projects/'+other['id']+'/assets',files={'file':('other.mp4',stream,'video/mp4')}).json()
    content=copy.deepcopy(row['content']);content['shot']['motionReference']['assetId']=foreign['id']
    assert save(team,row,content).status_code==422
    assert save(team,row,row['content'],client=team['viewer']).status_code==403
    response=team['viewer'].post('/api/projects/'+team['pid']+'/video-spec',json={
        'node_id':'motion-node','model_id':model,'shot':{'motionReference':content['shot']['motionReference']}})
    assert response.status_code==400,response.text
    assert team['viewer'].post('/api/projects/'+other['id']+'/video-spec',json={'node_id':'motion-node','model_id':model}).status_code in (403,404)
    assert team['a'].get(url(team,row)).json()==row


def test_project_default_change_preserves_override_and_only_invalidates_inherited_video(team,monkeypatch,media):
    model,row,_=setup_motion(team,monkeypatch,media)
    path='/api/projects/'+team['pid']
    project=team['admin'].get(path).json()
    response=team['admin'].patch(path+'/metadata',json={'expected_revision':project['revision'],'patch':{'videoReferenceMode':'first_frame'}})
    assert response.status_code==200,response.text
    assert team['a'].get(url(team,row)).json()==row  # explicit multimodal override remains untouched
    content=copy.deepcopy(row['content']);content['shot']['videoReferenceMode']=''
    response=save(team,row,content);assert response.status_code==200,response.text
    inherited=response.json()
    project=team['admin'].get(path).json()
    response=team['admin'].patch(path+'/metadata',json={'expected_revision':project['revision'],'patch':{'videoReferenceMode':'multimodal'}})
    assert response.status_code==200,response.text
    latest=team['a'].get(url(team,row)).json()
    assert latest['revision']==inherited['revision']+1
    assert latest['content']['nodes'][0]['data']['generation_revision']==2


@pytest.mark.parametrize('patch,error',[
    ({'fps':12},'帧率'),({'duration':1},'时长'),({'width':100},'尺寸'),({'video_codec':'vp9'},'H.264')])
def test_invalid_motion_metadata_is_rejected_before_decode(monkeypatch,media,patch,error):
    import shutil
    from backend import motion_references as motion
    name=uuid.uuid4().hex+'.mp4';target=s.ASSETS/name;shutil.copyfile(media,target)
    metadata=probe(target);monkeypatch.setattr(motion,'probe',lambda path:{**metadata,**patch})
    with pytest.raises(ValueError,match=error):
        inspect_motion({'kind':'video','path':name},{'max_reference_duration':30})


@pytest.mark.parametrize('kind,model_name',[
    ('hc_atom','doubao-seedance-2.5'),('volcengine_ark','doubao-seedance-2-5-260628'),
    ('runninghub','bytedance/seedance-2.5-token')])
def test_images_without_motion_or_dialogue_still_use_explicit_multimodal(team,monkeypatch,media,kind,model_name):
    import io
    from PIL import Image
    from backend.providers import hc_atom
    model,row,_=setup_motion(team,monkeypatch,media,kind,model_name)
    image=io.BytesIO();Image.new('RGB',(32,32),'blue').save(image,format='PNG')
    path='/api/projects/'+team['pid']
    asset=team['a'].post(path+'/assets',files={'file':('frame.png',image.getvalue(),'image/png')}).json()
    content=copy.deepcopy(row['content']);content['shot']['motionReference']=None
    content['nodes'][0]['data']['asset_ids']=[asset['id']]
    response=save(team,row,content);assert response.status_code==200,response.text
    job=submit_motion(team,model,asset_ids=[asset['id']])
    preview=team['viewer'].post(path+'/video-spec',json={'node_id':'motion-node','model_id':model})
    assert preview.status_code==200,preview.text
    assert preview.json()['reference_manifest']==job['input']['reference_manifest']
    assert len(job['input']['reference_manifest'])==1 and not job['input']['motion_reference']
    monkeypatch.setattr(hc_atom,'_register_seedance_asset',lambda *args:'asset://reviewed-frame')
    calls=[]
    def handle(request):
        if request.url.path.endswith('/media/upload/binary'):
            return httpx.Response(200,json={'code':0,'data':{'download_url':'https://media.example/frame.png'}})
        if request.method=='GET' or request.url.path.endswith('/query'):
            return httpx.Response(200,json={'status':'FAILED','error':'mock-terminal','errorMessage':'mock-terminal'})
        body=json.loads(request.content);calls.append(body)
        if kind=='runninghub':
            assert request.url.path.endswith('/multimodal-video')
            assert body['imageUrls']==['https://media.example/frame.png'] and 'firstFrameUrl' not in body
            assert body['omniReferenceTaskType']=='reference'
        else:
            assert [x.get('role') for x in body['content']]==[None,'reference_image']
            assert body['omni_reference_task_type']=='reference'
        assert body['ratio']=='16:9'
        return httpx.Response(200,json={'id':'image-only-reference','taskId':'image-only-reference'})
    mock_egress(monkeypatch,handle)
    from tests.test_hc_atom import NoWait
    worker=Worker();worker.halt=NoWait();s.job_update(job['id'],status='running')
    with pytest.raises(ValueError,match='mock-terminal'):worker.execute(job)
    assert len(calls)==1


def test_complete_visual_bindings_numbering_tail_conversion_and_idempotence(monkeypatch):
    from backend.providers import common
    assets={key:{'id':key,'kind':'image','name':key} for key in ('frame','tail','hero-image','scene-image','prop-image')}
    monkeypatch.setattr(common,'assets_by_ids',lambda job,ids:[assets[aid] for aid in ids])
    cards={key:{'id':key,'kind':kind,'name':key} for key,kind in [('hero','character'),('scene','scene'),('prop','prop')]}
    versions={key+'-v':{'id':key+'-v','cardId':key,'status':'locked','references':[{'role':'primary','assetId':key+'-image'}]} for key in cards}
    shot={'id':'shot','videoNode':'video','imageNode':'image','duration':2,'videoReferenceMode':'multimodal',
          'assetBindings':{'characters':[{'versionId':'hero-v'}],'scene':{'versionId':'scene-v'},'props':[{'versionId':'prop-v'}]}}
    document={'shots':[shot],'videoRatio':'9:16','filmBible':{'visual':{'cards':cards,'versions':versions}},
              'nodes':[{'id':'image','data':{'assetId':'frame'}},{'id':'video','data':{'end_asset_id':'tail'}}]}
    model={'capabilities':{'multimodal_reference':True,'max_references':9,'max_reference_duration':15,'max_video_duration':15},
           'rules':{'duration':{},'ratio':{}}}
    inp={'prompt':'人物站定','parameters':{'duration':2},'asset_ids':['frame','hero-image'],'end_asset_id':'tail'}
    result=compile_motion_input(document,'video','video',inp,'project',model)
    assert result['asset_ids']==['frame','tail','hero-image','scene-image','prop-image']
    assert [item['index'] for item in result['reference_manifest']]==[1,2,3,4,5]
    assert 'end_asset_id' not in result and '@图片3：hero' in result['prompt']
    assert result['parameters']=={'duration':4,'ratio':'9:16'} and '4 秒' in result['prompt']
    assert shot['duration']==2
    assert compile_motion_input(document,'video','video',result,'project',model)==result
    with pytest.raises(ValueError,match='不会截断'):
        compile_motion_input(document,'video','video',inp,'project',{**model,'capabilities':{**model['capabilities'],'max_references':4}})
    strict=copy.deepcopy(document);strict['shots'][0]['videoReferenceMode']='first_last_frame'
    with pytest.raises(ValueError,match='严格首帧'):
        compile_motion_input(strict,'video','video',inp,'project',model)


@pytest.mark.parametrize('batch',[False,True])
def test_explicit_strict_frame_uses_same_saved_reference_without_motion(team,monkeypatch,media,batch):
    import io
    from PIL import Image
    model,row,_=setup_motion(team,monkeypatch,media)
    path='/api/projects/'+team['pid']
    image=io.BytesIO();Image.new('RGB',(32,32),'green').save(image,format='PNG')
    asset=team['a'].post(path+'/assets',files={'file':('frame.png',image.getvalue(),'image/png')}).json()
    content=copy.deepcopy(row['content']);content['shot'].update(motionReference=None,videoReferenceMode='first_frame')
    content['nodes'][0]['data']['asset_ids']=[asset['id']]
    result=save(team,row,content);assert result.status_code==200,result.text
    job=submit_motion(team,model,batch,asset_ids=[asset['id']])
    preview=team['viewer'].post(path+'/video-spec',json={'node_id':'motion-node','model_id':model})
    assert preview.status_code==200,preview.text
    assert job['input']['generation_mode']['actual']=='first_frame'
    assert job['input']['reference_manifest']==preview.json()['reference_manifest']
    assert 'motion_reference' not in job['input'] and 'motion_compiler' not in job['input']


def test_pending_batch_frame_replaces_old_result_and_preserves_frozen_numbering(team,monkeypatch,media):
    import io
    from PIL import Image
    from tests.test_p5_canonical_integration import graph
    model,row,_=setup_motion(team,monkeypatch,media)
    image_model=uuid.uuid4().hex
    publish_test_model(team['admin'],image_model,kind='image',provider_type='volcengine_ark',
        upstream_model='doubao-seedream-5-0',url='https://provider.example',rules={},defaults={})
    image=io.BytesIO();Image.new('RGB',(32,32),'green').save(image,format='PNG')
    path='/api/projects/'+team['pid']
    asset=team['a'].post(path+'/assets',files={'file':('old.png',image.getvalue(),'image/png')}).json()
    content=copy.deepcopy(row['content']);content['shot']['imageNode']='pending-image'
    content['nodes'].append({'id':'pending-image','type':'media','data':{'kind':'image','prompt':'静态画面','model_id':image_model,'assetId':asset['id']}})
    structure=graph(team);edges=copy.deepcopy(structure['content']);edges['edges'].append({'id':'iv','source':'pending-image','target':'motion-node'})
    result=team['a'].post(url(team)+'/commands',json={'updates':[
        {'id':row['id'],**version(row),'content':content},{'id':structure['id'],**version(structure),'content':edges}]})
    assert result.status_code==200,result.text
    result=team['a'].post(path+'/run',json={'submission_id':uuid.uuid4().hex,'node_ids':['pending-image','motion-node'],'exact':True})
    assert result.status_code==200,result.text
    jobs=[team['a'].get('/api/jobs/'+jid).json() for jid in result.json()['job_ids']]
    parent=next(job for job in jobs if job['kind']=='image');video=next(job for job in jobs if job['kind']=='video')
    assert video['input']['image_reference_sources']==[{'type':'upstream_job','job_id':parent['id']}]
    assert video['input']['asset_ids']==[]
    assert video['input']['reference_manifest'][0]['source']=={'type':'upstream_node','node_id':'pending-image'}
    captured=[];worker=Worker();monkeypatch.setattr(worker,'dispatch',lambda job,provider:captured.append(job) or {})
    s.job_update(parent['id'],status='succeeded',result={'assets':[asset]})
    s.job_update(video['id'],status='running');worker.execute(video)
    assert captured[0]['input']['asset_ids']==[asset['id']]
    # Terminal jobs are immutable through job_update. Simulate a different
    # provider result only inside this isolated fixture, not via product APIs.
    with s.db() as c:
        c.execute('UPDATE jobs SET result=%s WHERE id=%s',(s.dumps({'assets':[asset,asset]}),parent['id']))
    with pytest.raises(ValueError,match='恰好一张'):worker.execute(video)
    assert len(captured)==1


@pytest.mark.parametrize('kind,model_name',[
    ('hc_atom','doubao-seedance-2.5'),('volcengine_ark','doubao-seedance-2-5-260628'),
    ('runninghub','bytedance/seedance-2.5-token')])
def test_motion_and_adopted_dialogue_share_preview_and_real_compiled_audio(team,monkeypatch,media,tmp_path,kind,model_name):
    from tests.test_upstream_hc_dialogue import setup_dialogue,submit_video
    from tests.test_p5_object_candidates import audio_result,candidate
    row,_,audio_job=setup_dialogue(team,monkeypatch)
    audio=audio_result(audio_job,tmp_path)
    response=team['a'].post(candidate(team,audio_job)+'/adopt',json=version(row))
    assert response.status_code==200,response.text
    row=response.json()['target'];model=uuid.uuid4().hex
    publish_test_model(team['admin'],model,kind='video',provider_type=kind,upstream_model=model_name,
        url='https://provider.example',options={'public_base_url':'https://studio.example'},
        capabilities={'audio_reference':True,'multimodal_reference':True,'video_reference':True},
        rules={'duration':{'type':'integer','min':4,'max':30},'ratio':{'type':'string','enum':['16:9']},'generate_audio':{'type':'boolean'}},
        defaults={'duration':4,'ratio':'16:9','generate_audio':False})
    path='/api/projects/'+team['pid']
    video=team['a'].post(path+'/assets',files={'file':('motion.mp4',media.read_bytes(),'video/mp4')}).json()
    content=copy.deepcopy(row['content']);content['shot'].update(videoReferenceMode='multimodal',motionReference={'assetId':video['id'],'cameraMode':'follow_reference'})
    content['nodes'][0]['data']['model_id']=model
    response=save(team,row,content);assert response.status_code==200,response.text
    response=submit_video(team,model);assert response.status_code==200,response.text
    job=response.json()
    preview=team['viewer'].post(path+'/video-spec',json={'node_id':'hc-video','model_id':model})
    assert preview.status_code==200,preview.text
    assert preview.json()['reference_manifest']==job['input']['reference_manifest']
    assert preview.json()['prompt']==job['input']['prompt']
    assert job['input']['dialogue_audio_asset_ids']==[audio['id']] and '@音频1' in job['input']['prompt']
    calls=[];uploads=[]
    def handle(request):
        if request.url.path.endswith('/media/upload/binary'):
            uploads.append(request.content)
            return httpx.Response(200,json={'code':0,'data':{'download_url':f'https://media.example/{len(uploads)}'}})
        if request.method=='GET' or request.url.path.endswith('/query'):
            return httpx.Response(200,json={'status':'FAILED','error':'mock-terminal','errorMessage':'mock-terminal'})
        body=json.loads(request.content);calls.append(body)
        if kind=='runninghub':
            assert body['audioUrls']==['https://media.example/2'] and body['videoUrls']==['https://media.example/1']
            assert body['generateAudio'] is True
        else:
            audio_ref=next(item for item in body['content'] if item.get('role')=='reference_audio')
            assert audio_ref['audio_url']['url'].startswith('https://studio.example/' if kind=='hc_atom' else 'data:audio/mpeg;base64,')
            assert body['generate_audio'] is True
        return httpx.Response(200,json={'id':'combined-remote','taskId':'combined-remote'})
    mock_egress(monkeypatch,handle)
    from tests.test_hc_atom import NoWait
    worker=Worker();worker.halt=NoWait();s.job_update(job['id'],status='running')
    with pytest.raises(ValueError,match='mock-terminal'):worker.execute(job)
    assert len(calls)==1
    if kind=='runninghub':assert b'audio/mpeg' in uploads[1]
