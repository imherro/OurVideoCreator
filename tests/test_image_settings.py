"""Platform-controlled image settings; local previews and real PG admission."""
import json

import pytest
from backend import image_settings, platform_models, store as s
from tests.platform_model_helpers import admin, publish_test_model
from tests.test_p4_submission_execution import project, submit
from tests.test_p4_r1_regressions import ordinary_editor
from tests.test_p5_object_transactions import team
from tests.test_p3_identity_acl import clients
from tests.collaboration_helpers import create_node, create_object


def spec_model(admin, kind='maestro', **overrides):
    return publish_test_model(admin,s.uid('image-spec-'),kind='image',provider_type=kind,
        upstream_model='test-image',rules=overrides.get('rules',{
            'resolution':{'type':'string'},'seed':{'type':'integer','min':-1,'max':100}}),
        defaults=overrides.get('defaults',{'resolution':'1024x1024','seed':-1}),
        options=overrides.get('options',{}),capabilities=overrides.get('capabilities',{}))


def test_preview_does_not_write_and_submission_uses_same_spec_and_seed_receipt(admin):
    model=spec_model(admin)
    p=project(admin);pid=p['id']
    with ordinary_editor(admin,p) as client:
        before=client.get(f'/api/projects/{pid}').json()
        body={'node_id':'p4-image','model_id':model['id'],'imageSettings':{'sizeMode':'custom','size':'1280x720','seed':-1}}
        preview=client.post(f'/api/projects/{pid}/image-spec',json=body)
        assert preview.status_code==200,preview.text
        spec=preview.json()
        assert spec['size']=='1280x720' and spec['seed']==-1
        assert client.get(f'/api/projects/{pid}/jobs').json()==[]
        assert client.get(f'/api/projects/{pid}').json()==before
        inp={'model_id':model['id'],'prompt':'test','imageSettings':body['imageSettings'],
             'image_spec':{'seed':999,'size':'1x1'}}
        job=submit(client,pid,model['id'],kind='image',input=inp).json()
        actual=job['input']['image_spec']
        assert actual['size']==spec['size'] and 0<=actual['seed']<=100
        with s.db() as c:
            private=platform_models.load_job_provider(c,job['id'])['job_parameters']
        assert private==actual['parameters'] and private['seed']==actual['seed']
        request={'node_id':job['node_id'],'kind':'image','submission_id':job['submission_id'],'input':inp}
        replay=client.post(f'/api/projects/{pid}/jobs',json=request)
        assert replay.status_code==200,replay.text
        assert replay.json()==job
        changed={**request,'input':{**inp,'imageSettings':{**body['imageSettings'],'size':'1536x864'}}}
        assert client.post(f'/api/projects/{pid}/jobs',json=changed).status_code==409
        assert len(client.get(f'/api/projects/{pid}/jobs').json())==1
        # Replaying public server metadata is harmless, never a writable spec.
        request['input']=job['input']
        assert client.post(f'/api/projects/{pid}/jobs',json=request).status_code==200


@pytest.mark.parametrize('settings', [
    {'sizeMode':'custom','size':'1024x1024'}, {'sizeMode':'custom','size':'1279x720'},
    {'sizeMode':'custom','size':'8192x4608'}, {'seed':True}, {'seed':101}, {'sizeMode':'bogus'},
])
def test_invalid_image_settings_are_rejected_in_preview_and_submit(admin,settings):
    model=spec_model(admin);pid=project(admin)['id']
    preview=admin.post(f'/api/projects/{pid}/image-spec',json={
        'node_id':'p4-image','model_id':model['id'],'imageSettings':settings})
    assert preview.status_code==400,preview.text
    response=submit(admin,pid,model['id'],kind='image',input={
        'model_id':model['id'],'prompt':'test','imageSettings':settings})
    assert response.status_code==400,response.text
    assert admin.get(f'/api/projects/{pid}/jobs').json()==[]


def test_cloud_preview_unsaved_frame_and_no_unpublished_custom_controls(admin):
    model=spec_model(admin,'runninghub',rules={'size':{'type':'string'},'resolution':{'type':'string','enum':['2k']}},
        defaults={'size':'1024x1024','resolution':'2k'})
    pid=project(admin)['id']
    body={'node_id':'p4-image','model_id':model['id'],'ratio':'9:16'}
    response=admin.post(f'/api/projects/{pid}/image-spec',json=body)
    assert response.status_code==200,response.text
    spec=response.json()
    assert spec['parameters']=={'size':'1152x2048','resolution':'2k'}
    assert spec['seedSupported'] is False and spec['seed'] is None
    assert len(spec['sizeOptions'])==1
    for settings in ({'sizeMode':'custom','size':'1152x2048'},{'seed':3}):
        assert admin.post(f'/api/projects/{pid}/image-spec',json={**body,'imageSettings':settings}).status_code==400
    assert admin.get(f'/api/projects/{pid}').json()['document']['ratio']=='16:9'
    job=submit(admin,pid,model['id'],kind='image').json()
    assert job['input']['image_spec']['size']=='2048x1152'


def test_comfy_capabilities_come_from_private_template_and_admin_rules():
    definition={'rules':{'resolution':{'type':'string'},'seed':{'type':'integer','min':-1,'max':100}},
        'defaults':{'resolution':'1024x1024','seed':-1},'capabilities':{}}
    config={'type':'comfy','options':{'workflow':{'1':{'inputs':{
        'width':'{{width}}','height':'{{height}}','seed':'{{seed}}'}}}}}
    result,spec=image_settings.resolve(definition,{}, {'ratio':'16:9','videoResolution':'480p'},'image',config,
        {'sizeMode':'video','seed':7})
    assert result=={'resolution':'848x480','seed':7}
    assert spec['size']=='848x480' and spec['seedSupported']
    for config in ({'type':'comfy','options':{}},{'type':'openai'}):
        with pytest.raises(ValueError,match='尺寸'):
            image_settings.resolve(definition,{}, {'ratio':'16:9'},'image',config,{'sizeMode':'custom','size':'1280x720'})
    definition['rules']['resolution']['enum']=['2048x1152']
    definition['defaults']['resolution']='2048x1152'
    with pytest.raises(ValueError,match='枚举'):
        image_settings.resolve(definition,{}, {'ratio':'16:9'},'image',{'type':'maestro'},
            {'sizeMode':'custom','size':'1280x720'})


def test_preview_viewer_acl_and_reference_requirement_does_not_trigger_external_io(team,monkeypatch):
    from tests.platform_model_helpers import MASTER
    from backend import provider_secrets, provider_egress
    monkeypatch.setenv(provider_secrets.KEY_ENV,MASTER)
    monkeypatch.setenv(provider_secrets.KEY_ID_ENV,'p4-test')
    model=spec_model(team['admin'],capabilities={'image_reference':True,'requires_reference':True})
    monkeypatch.setattr(provider_egress,'client',lambda **kw:pytest.fail('preview attempted external I/O'))
    body={'node_id':'not-yet-saved','model_id':model['id']}
    before=team['viewer'].get('/api/projects/'+team['pid']).json()
    response=team['viewer'].post('/api/projects/'+team['pid']+'/image-spec',json=body)
    assert response.status_code==200,response.text
    assert team['viewer'].get('/api/projects/'+team['pid']).json()==before
    foreign=project(team['admin'])['id']
    assert team['viewer'].post('/api/projects/'+foreign+'/image-spec',json=body).status_code in (403,404)
    assert team['viewer'].post('/api/projects/'+team['pid']+'/image-spec',json={
        **body,'imageSettings':{'url':'https://forged.example'}}).status_code==400
    assert submit(team['admin'],team['pid'],model['id'],kind='image').status_code==400


def test_single_and_batch_keep_explicit_settings_and_replay_random_seed(admin):
    model=spec_model(admin);pid=project(admin)['id']
    data={'model_id':model['id'],'prompt':'test','parameters':{'resolution':'1024x1024','seed':-1},
          'imageSettings':{'sizeMode':'custom','size':'1280x720','seed':-1}}
    create_node(admin,pid,'single','image',**data)
    create_object(admin,pid,'shot',{'shot':{'id':'spec-shot','uid':'spec-shot','imageNode':'batch','image_prompt':'test'},
        'nodes':[{'id':'batch','type':'media','data':{'kind':'image',**data}}]})
    single=submit(admin,pid,model['id'],kind='image',node_id='single',input=data).json()
    request={'submission_id':s.uid('image-batch-'),'node_ids':['batch'],'exact':True}
    response=admin.post(f'/api/projects/{pid}/run',json=request)
    assert response.status_code==200,response.text
    batch=admin.get('/api/jobs/'+response.json()['job_ids'][0]).json()
    for job in (single,batch):
        assert job['input']['image_spec']['size']=='1280x720'
        assert 0<=job['input']['image_spec']['seed']<=100
    repeated=admin.post(f'/api/projects/{pid}/run',json=request)
    assert repeated.status_code==200,repeated.text
    assert repeated.json()==response.json()
    assert admin.get('/api/jobs/'+batch['id']).json()['input']['image_spec']==batch['input']['image_spec']


@pytest.mark.parametrize('provider_type',['maestro','comfy'])
def test_worker_sends_frozen_custom_pixels_and_seed(admin,monkeypatch,provider_type):
    import io
    import httpx
    from PIL import Image
    from backend.worker import Worker
    from tests.egress_helpers import mock_egress
    from tests.test_runninghub import NoWait
    workflow={'1':{'inputs':{'width':'{{width}}','height':'{{height}}','seed':'{{seed}}'}}}
    model=spec_model(admin,provider_type,options={'workflow':workflow} if provider_type=='comfy' else {})
    pid=project(admin)['id']
    job=submit(admin,pid,model['id'],kind='image',input={'model_id':model['id'],'prompt':'test',
        'imageSettings':{'sizeMode':'custom','size':'1280x720','seed':-1}}).json()
    png=io.BytesIO();Image.new('RGB',(2,2),'blue').save(png,format='PNG')
    sent=[]
    def handle(request):
        path=request.url.path
        if path=='/v1/api/v1/models':
            return httpx.Response(200,json={'models':[{'model_type':'test-image','director':{'image':{'compatible':True}}}]})
        if path=='/v1/api/v1/defaults/test-image':return httpx.Response(200,json={'defaults':{'seed':999,'resolution':'512x512'}})
        if path in ('/v1/prompt','/v1/api/v1/generate'):
            sent.append(json.loads(request.read()))
            return httpx.Response(200,json={'job_id':'test-handle','prompt_id':'test-handle'})
        if path=='/v1/api/v1/status/test-handle':return httpx.Response(200,json={'status':'completed','output_files':['test.png']})
        if path=='/v1/history/test-handle':return httpx.Response(200,json={'test-handle':{'outputs':{'1':{'images':[{'filename':'test.png'}]}}}})
        if path in ('/v1/view','/v1/api/v1/uploads/test.png'):return httpx.Response(200,content=png.getvalue())
        pytest.fail('Unexpected mock protocol path: '+path)
    mock_egress(monkeypatch,handle)
    assert s.job_update(job['id'],status='running')
    worker=Worker();worker.halt=NoWait()
    assert worker.execute(job)['assets']
    assert len(sent)==1
    body=sent[0] if provider_type=='maestro' else sent[0]['prompt']['1']['inputs']
    assert body['seed']==job['input']['image_spec']['seed']
    if provider_type=='maestro':assert body['resolution']=='1280x720'
    else:assert (body['width'],body['height'])==(1280,720)


def test_batch_does_not_inject_conflicting_top_level_ratio_alias(admin):
    model=spec_model(admin,'runninghub',rules={'size':{'type':'string'},'ratio':{'type':'string','enum':['1:1','16:9']}},
        defaults={'size':'1024x1024','ratio':'1:1'})
    pid=project(admin)['id']
    create_node(admin,pid,'ratio-image','image',model_id=model['id'],prompt='test',parameters={'ratio':'1:1'})
    response=admin.post(f'/api/projects/{pid}/run',json={
        'submission_id':s.uid('alias-batch-'),'node_ids':['ratio-image'],'exact':True})
    assert response.status_code==200,response.text
    job=admin.get('/api/jobs/'+response.json()['job_ids'][0]).json()
    assert job['input']['image_spec']['parameters']['ratio']=='16:9'


def test_preview_validates_random_seed_domain_without_drawing_and_exact_replay_uses_original_rules(admin,monkeypatch):
    monkeypatch.setattr(image_settings.secrets,'randbelow',lambda count: min(75,count-1))
    model=spec_model(admin);pid=project(admin)['id']
    job=submit(admin,pid,model['id'],kind='image').json()
    assert job['input']['image_spec']['seed']==75
    changed={**model['definition'],'rules':{'resolution':{'type':'string','enum':['2048x1152']},
        'seed':{'type':'integer','min':-1,'max':1}},'defaults':{'resolution':'2048x1152','seed':-1}}
    response=admin.put('/api/admin/models/'+model['id'],json={'revision':model['revision'],'kind':'image',
        'provider_id':model['provider_id'],'published':True,'enabled':True,'definition':changed})
    assert response.status_code==200,response.text
    replay=admin.post(f'/api/projects/{pid}/jobs',json={'node_id':job['node_id'],'kind':'image',
        'submission_id':job['submission_id'],'input':job['input']})
    assert replay.status_code==200,replay.text
    assert replay.json()['input']['image_spec']['seed']==75
    definition={'rules':{'seed':{'type':'integer','enum':[-1]}},'defaults':{'seed':-1},'capabilities':{}}
    with pytest.raises(ValueError,match='可冻结'):
        image_settings.resolve(definition,{}, {'ratio':'16:9'},'i',{'type':'maestro'})
    definition['rules']['seed']['enum']=[-1,4,8]
    monkeypatch.setattr(image_settings.secrets,'choice',lambda values:pytest.fail('preview drew a random seed'))
    _,spec=image_settings.resolve(definition,{}, {'ratio':'16:9'},'i',{'type':'maestro'})
    assert spec['seed']==-1


def test_preview_includes_legacy_top_level_controls_in_the_same_validation(admin):
    model=spec_model(admin);pid=project(admin)['id']
    for legacy,parameters,status in [({'seed':7},{},200),({'seed':7},{'seed':-1},400),
                                     ({'provider':'forged'},{},400)]:
        response=admin.post(f'/api/projects/{pid}/image-spec',json={'node_id':'p4-image','model_id':model['id'],
            'node_data':legacy,'parameters':parameters})
        assert response.status_code==status,response.text
        actual=submit(admin,pid,model['id'],kind='image',input={**legacy,'model_id':model['id'],
            'parameters':parameters,'prompt':'test'})
        assert actual.status_code==status,actual.text
        if status==200:
            assert response.json()['seed']==actual.json()['input']['image_spec']['seed']==7
