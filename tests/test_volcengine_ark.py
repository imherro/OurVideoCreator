import base64
import json
import time
import uuid
import wave

import httpx
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from backend.app import app
from tests.auth_helpers import login_admin
from tests.collaboration_helpers import create_node
from tests.platform_model_helpers import bind_adapter_job
from tests.egress_helpers import mock_egress
from backend import store as s
from backend import worker as worker_module
from backend.providers import common, volcengine_ark as ark
from backend.worker import Worker, checked

s.init()


def stored_job(kind, provider, provider_job_id=None):
    with TestClient(app) as client:
        login_admin(client)
        response = client.post('/api/projects', json={'name': 'Ark test'})
        assert response.status_code == 200, response.text
        pid = response.json()['id']
        create_node(client, pid, 'node', kind)
    jid='ark-job-'+uuid.uuid4().hex
    now=time.time()
    inp={'provider':provider['id'],'allow_cloud':True,'prompt':'电影感机器人走向窗前'}
    with s.db() as db:
        db.execute('INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,provider_job_id,created,updated) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                   (jid,'ark-submit-'+uuid.uuid4().hex,pid,'node',kind,'running',s.dumps(inp),provider_job_id,now,now))
        bind_adapter_job(db,jid,kind,provider,inp)
    return {'id':jid,'project_id':pid,'node_id':'node','kind':kind,'status':'running','input':inp,'provider_job_id':provider_job_id}


class NoWait:
    def wait(self, seconds): return False
    def is_set(self): return False


def provider():
    return {
        'id':'ark','type':'volcengine_ark','local':False,
        'url':'https://ark.example/api/v3','api_key':'secret',
        'models':{'text':'doubao-text','image':'seedream-image','video':'seedance-video'},
        'parameters':{'video':{'duration':5,'resolution':'720p','ratio':'16:9','generate_audio':True,'poll_interval':1}},
    }


def add_image_asset(item, name, color, size=(32,24)):
    aid='ark-ref-'+uuid.uuid4().hex
    path=s.ASSETS/(aid+'.png')
    Image.new('RGB',size,color).save(path)
    with s.db() as db:
        db.execute('INSERT INTO assets(id,project_id,name,kind,path,mime,metadata,created) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(
            aid,item['project_id'],name,'image',path.name,'image/png',s.dumps({'width':size[0],'height':size[1]}),time.time()
        ))
    return aid,path.read_bytes()


def add_audio_asset(item, name='对白'):
    aid='ark-audio-'+uuid.uuid4().hex
    path=s.ASSETS/(aid+'.wav')
    with wave.open(str(path),'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b'\x00\x00'*12000)
    with s.db() as db:
        db.execute('INSERT INTO assets(id,project_id,name,kind,path,mime,metadata,created) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(
            aid,item['project_id'],name,'audio',path.name,'audio/wav',s.dumps({'duration':.5}),time.time()
        ))
    return aid


def test_ark_text_reuses_openai_compatible_worker(monkeypatch):
    item=stored_job('text',provider())
    original=httpx.Client
    def handle(request):
        assert request.url.path=='/api/v3/chat/completions'
        body=json.loads(request.read())
        assert body['model']=='doubao-text' and body['stream'] is True
        return httpx.Response(200,content=b'data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n')
    mock_egress(monkeypatch,handle)
    assert Worker().execute(item)=={'text':'OK'}


def test_seedream_downloads_into_existing_asset_library(monkeypatch):
    item=stored_job('image',provider())
    original=httpx.Client
    def handle(request):
        assert request.url.path=='/api/v3/images/generations'
        body=json.loads(request.read())
        assert body['model']=='seedream-image' and body['response_format']=='url'
        assert 'image' not in body
        return httpx.Response(200,json={'data':[{'url':'https://result.example/frame.png'}]})
    mock_egress(monkeypatch,handle)
    monkeypatch.setattr(common,'download_result',lambda job,url,ext:{'id':'asset-image','kind':'image','url':'/api/assets/asset-image/file'})
    assert Worker().execute(item)['assets'][0]['id']=='asset-image'


@pytest.mark.parametrize('count',[1,2])
def test_seedream_resolves_ordered_local_references_as_data_uris(monkeypatch,count):
    item=stored_job('image',provider())
    expected=[];asset_ids=[]
    for index,color in enumerate(((255,0,0),(0,0,255))[:count]):
        aid,data=add_image_asset(item,f'参考图 {index+1}',color)
        asset_ids.append(aid);expected.append(data)
    item['input']['asset_ids']=asset_ids
    original=httpx.Client
    def handle(request):
        body=json.loads(request.read())
        references=body['image'] if isinstance(body['image'],list) else [body['image']]
        assert len(references)==count
        assert [base64.b64decode(value.split(',',1)[1]) for value in references]==expected
        assert all(value.startswith('data:image/png;base64,') for value in references)
        return httpx.Response(200,json={'data':[{'url':'https://result.example/frame.png'}]})
    mock_egress(monkeypatch,handle)
    monkeypatch.setattr(common,'download_result',lambda job,url,ext:{'id':'asset-image','kind':'image'})
    assert Worker().execute(item)['assets'][0]['id']=='asset-image'


def test_seedream_reference_limit_is_provider_configurable(monkeypatch):
    p=provider();p['parameters']['image']={'max_references':1}
    item=stored_job('image',p)
    item['input']['asset_ids']=[add_image_asset(item,'一',(1,2,3))[0],add_image_asset(item,'二',(3,2,1))[0]]
    with pytest.raises(ValueError,match='参考图或数量超限'):
        Worker().execute(item)


def test_seedance_persists_task_and_resume_only_queries(monkeypatch):
    p=provider();p['parameters']['video']['duration']=2;item=stored_job('video',p)
    calls=[];downloads=[];original=httpx.Client
    def handle(request):
        calls.append((request.method,request.url.path))
        if request.method=='POST':
            body=json.loads(request.read())
            assert body['model']=='seedance-video' and body['content'][0]['type']=='text'
            assert body['ratio']=='16:9'
            assert body['duration']==2
            return httpx.Response(200,json={'id':'ark-task-1','status':'queued'})
        return httpx.Response(200,json={'id':'ark-task-1','status':'succeeded','content':{'video_url':'https://result.example/movie.mp4'}})
    mock_egress(monkeypatch,handle)
    def download(job,url,ext,recoverable=False):
        downloads.append((url,ext,recoverable))
        return {'id':'asset-video','kind':'video'}
    monkeypatch.setattr(common,'download_result',download)
    worker=Worker();worker.halt=NoWait()
    assert worker.execute(item)['assets'][0]['id']=='asset-video'
    with s.db() as db:
        assert db.execute('SELECT provider_job_id FROM jobs WHERE id=%s',(item['id'],)).fetchone()['provider_job_id']=='ark-task-1'
    assert calls==[('POST','/api/v3/contents/generations/tasks'),('GET','/api/v3/contents/generations/tasks/ark-task-1')]

    resumed=stored_job('video',p,'existing-task')
    # Once Ark has accepted an I2V task, resume must only poll the durable task
    # id and must not need to reload or re-encode the original first frame.
    resumed['input']['asset_ids']=['source-no-longer-needed-for-polling']
    calls.clear()
    assert worker.execute(resumed)['assets'][0]['id']=='asset-video'
    assert calls==[('GET','/api/v3/contents/generations/tasks/existing-task')]
    assert downloads==[
        ('https://result.example/movie.mp4','.mp4',True),
        ('https://result.example/movie.mp4','.mp4',True),
    ]


def test_seedance_25_short_shot_uses_provider_minimum_without_changing_plan():
    model = 'doubao-seedance-2-5-260628'
    assert ark.seedance_submission_duration(model, 1) == 4
    assert ark.seedance_submission_duration(model, 3) == 4
    assert ark.seedance_submission_duration(model, 4) == 4
    assert ark.seedance_submission_duration(model, 6) == 6
    prompt = '动作。\n\n[镜头时长]\n本镜头成片总时长必须为 3 秒；所有动作在这段时间内完成。'
    submitted = ark.seedance_submission_prompt(prompt, 3, 4)
    assert '本次模型生成长度为 4 秒；核心动作须在前 3 秒内完成' in submitted
    assert '本镜头成片总时长必须为 3 秒' not in submitted


def test_seedance_25_sends_locked_dialogue_as_audio_reference(monkeypatch):
    configured=provider();configured['models']['video']='doubao-seedance-2-5-260628'
    item=stored_job('video',configured)
    frame_id,_=add_image_asset(item,'对白镜头首帧',(24,48,96))
    item['input']['asset_ids']=[frame_id]
    item['input']['dialogue_audio']=[{'assetId':'voice-1','start':.3,'duration':1.2}]
    item['input']['dialogue_audio_asset_ids']=['voice-1']
    item['input']['dialogue_audio_mode']='seedance_reference'
    original=httpx.Client;submitted=[]
    def handle(request):
        if request.method=='POST':
            body=json.loads(request.read());submitted.append(body)
            return httpx.Response(200,json={'id':'dialogue-video'})
        return httpx.Response(200,json={'status':'succeeded','content':{'video_url':'https://result.example/dialogue.mp4'}})
    mock_egress(monkeypatch,handle)
    monkeypatch.setattr(ark,'_dialogue_reference_audio',lambda job,duration:'data:audio/mpeg;base64,ZmFrZQ==')
    monkeypatch.setattr(common,'download_result',lambda job,url,ext,recoverable=False:{'id':'referenced-video','kind':'video'})
    worker=Worker();worker.halt=NoWait()
    assert worker.execute(item)['assets'][0]['id']=='referenced-video'
    body=submitted[0]
    assert body['generate_audio'] is True
    assert body['omni_reference_task_type']=='reference'
    assert body['ratio']=='16:9'
    assert body['content'][1]['role']=='reference_image'
    assert all(part.get('role') not in ('first_frame','last_frame') for part in body['content'])
    assert body['content'][-1]=={
        'type':'audio_url','audio_url':{'url':'data:audio/mpeg;base64,ZmFrZQ=='},'role':'reference_audio',
    }
    assert '@图片1' in body['content'][0]['text'] and '@音频1' in body['content'][0]['text']


def test_seedance_dialogue_reference_preserves_timing_in_one_audio_file(tmp_path):
    item=stored_job('video',provider())
    aid=add_audio_asset(item)
    item['input']['dialogue_audio']=[{'assetId':aid,'start':.5,'duration':.5}]
    uri=ark._dialogue_reference_audio(item,4)
    assert uri.startswith('data:audio/mpeg;base64,')
    rendered=tmp_path/'reference.mp3'
    rendered.write_bytes(base64.b64decode(uri.split(',',1)[1]))
    metadata=ark.probe(rendered)
    assert float(metadata['duration']) == pytest.approx(4,abs=.1)


def test_seedance_legacy_dialogue_job_still_uses_exact_audio_mux(monkeypatch,tmp_path):
    item=stored_job('video',provider())
    item['input']['dialogue_audio']=[{'assetId':'voice-1','start':.3,'duration':1.2}]
    original=httpx.Client;submitted=[]
    def handle(request):
        if request.method=='POST':
            submitted.append(json.loads(request.read()))
            return httpx.Response(200,json={'id':'legacy-dialogue-video'})
        return httpx.Response(200,json={'status':'succeeded','content':{'video_url':'https://result.example/dialogue.mp4'}})
    mock_egress(monkeypatch,handle)
    downloaded=tmp_path/'silent.mp4';downloaded.write_bytes(b'video')
    monkeypatch.setattr(common,'download_file',lambda *args,**kwargs:downloaded)
    monkeypatch.setattr(ark,'_mux_fixed_dialogue',lambda worker,job,path:{'id':'fixed-voice-video','kind':'video'})
    worker=Worker();worker.halt=NoWait()
    assert worker.execute(item)['assets'][0]['id']=='fixed-voice-video'
    assert submitted[0]['generate_audio'] is False
    assert 'omni_reference_task_type' not in submitted[0]


def test_seedance_sends_one_local_image_as_first_frame(monkeypatch):
    p=provider();item=stored_job('video',p)
    aid,expected=add_image_asset(item,'首帧',(24,48,96))
    item['input']['asset_ids']=[aid]
    original=httpx.Client
    calls=[]
    def handle(request):
        calls.append((request.method,request.url.path))
        if request.method=='POST':
            body=json.loads(request.read())
            assert body['content'][0]=={'type':'text','text':item['input']['prompt']}
            assert 'ratio' not in body
            frame=body['content'][1]
            assert frame['type']=='image_url' and frame['role']=='first_frame'
            assert base64.b64decode(frame['image_url']['url'].split(',',1)[1])==expected
            return httpx.Response(200,json={'id':'i2v-task'})
        return httpx.Response(200,json={'id':'i2v-task','status':'succeeded','content':{'video_url':'https://result.example/i2v.mp4'}})
    mock_egress(monkeypatch,handle)
    monkeypatch.setattr(common,'download_result',lambda job,url,ext,recoverable=False:{'id':'i2v-result','kind':'video'})
    worker=Worker();worker.halt=NoWait()
    assert worker.execute(item)['assets'][0]['id']=='i2v-result'
    assert calls==[('POST','/api/v3/contents/generations/tasks'),('GET','/api/v3/contents/generations/tasks/i2v-task')]


def test_seedance_rejects_more_than_one_first_frame():
    item=stored_job('video',provider())
    item['input']['asset_ids']=[add_image_asset(item,'一',(1,2,3))[0],add_image_asset(item,'二',(3,2,1))[0]]
    with pytest.raises(ValueError,match='参考图或数量超限'):
        Worker().execute(item)


def test_seedance_sends_first_and_last_frames_in_role_order(monkeypatch):
    item=stored_job('video',provider())
    first_id,first_bytes=add_image_asset(item,'首帧',(12,34,56))
    last_id,last_bytes=add_image_asset(item,'尾帧',(65,43,21),(64,48))
    item['input'].update(asset_ids=[first_id],end_asset_id=last_id)
    original=httpx.Client
    def handle(request):
        if request.method=='POST':
            body=json.loads(request.read())
            assert [part.get('role') for part in body['content']]==[None,'first_frame','last_frame']
            assert 'ratio' not in body
            images=[base64.b64decode(part['image_url']['url'].split(',',1)[1]) for part in body['content'][1:]]
            assert images==[first_bytes,last_bytes]
            return httpx.Response(200,json={'id':'fl2v-task'})
        return httpx.Response(200,json={'status':'succeeded','content':{'video_url':'https://result.example/fl2v.mp4'}})
    mock_egress(monkeypatch,handle)
    monkeypatch.setattr(common,'download_result',lambda job,url,ext,recoverable=False:{'id':'fl2v-result','kind':'video'})
    worker=Worker();worker.halt=NoWait()
    assert worker.execute(item)['assets'][0]['id']=='fl2v-result'


def test_seedance_rejects_mismatched_first_and_last_frame_ratios():
    item=stored_job('video',provider())
    item['input'].update(
        asset_ids=[add_image_asset(item,'首帧',(1,2,3),(32,24))[0]],
        end_asset_id=add_image_asset(item,'尾帧',(3,2,1),(32,32))[0],
    )
    with pytest.raises(ValueError,match='宽高比必须一致'):
        Worker().execute(item)


def test_seedance_cancel_requests_remote_delete(monkeypatch):
    calls=[];original=httpx.Client
    def handle(request):
        calls.append((request.method,request.url.path))
        return httpx.Response(204)
    mock_egress(monkeypatch,handle)
    assert ark.cancel({'provider_job_id':'task-to-cancel'},provider()) is True
    assert calls==[('DELETE','/api/v3/contents/generations/tasks/task-to-cancel')]


@pytest.mark.parametrize('status',[429,500,503])
def test_seedance_poll_failure_keeps_existing_task_recoverable(monkeypatch,status):
    item=stored_job('video',provider(),'existing-task')
    original=httpx.Client
    def handle(request):
        assert request.method=='GET'
        return httpx.Response(status,json={'error':{'message':'temporary'}})
    mock_egress(monkeypatch,handle)
    worker=Worker();worker.halt=NoWait()
    with pytest.raises(common.RecoverableProviderError):
        worker.execute(item)
    with s.db() as db:
        assert db.execute('SELECT provider_job_id FROM jobs WHERE id=%s',(item['id'],)).fetchone()['provider_job_id']=='existing-task'


def test_worker_marks_recoverable_provider_error_interrupted(monkeypatch):
    item=stored_job('video',provider(),'existing-task')
    with s.db() as db:
        db.execute("UPDATE jobs SET status='queued',created=-1 WHERE id=%s",(item['id'],))
    worker=Worker()
    def execute(job):
        worker.halt.set()
        raise common.RecoverableProviderError('temporary polling error')
    monkeypatch.setattr(worker,'execute',execute)
    worker.process_lock.acquire()
    try:
        worker.loop()
    finally:
        worker.process_lock.release()
    with s.db() as db:
        row=db.execute('SELECT status,provider_job_id,phase FROM jobs WHERE id=%s',(item['id'],)).fetchone()
    assert row['status']=='interrupted' and row['provider_job_id']=='existing-task'
    assert '可恢复查询' in row['phase']


def test_seedance_cancel_race_persists_remote_task_id(monkeypatch):
    item=stored_job('video',provider())
    calls=[];original=httpx.Client
    def handle(request):
        calls.append((request.method,request.url.path))
        if request.method=='POST':
            s.job_update(item['id'],status='cancelled',phase='已请求取消')
            return httpx.Response(200,json={'id':'paid-task-after-cancel'})
        return httpx.Response(204)
    mock_egress(monkeypatch,handle)
    worker=Worker();worker.halt=NoWait()
    with pytest.raises(InterruptedError):
        worker.execute(item)
    with s.db() as db:
        row=db.execute('SELECT status,provider_job_id,phase FROM jobs WHERE id=%s',(item['id'],)).fetchone()
    assert row['status']=='cancelled' and row['provider_job_id']=='paid-task-after-cancel'
    assert '已请求供应商取消' in row['phase']
    assert calls==[('POST','/api/v3/contents/generations/tasks'),('DELETE','/api/v3/contents/generations/tasks/paid-task-after-cancel')]


def test_seedance_expired_status_is_explicit(monkeypatch):
    item=stored_job('video',provider(),'expired-task')
    original=httpx.Client
    mock_egress(monkeypatch,
        lambda request:httpx.Response(200,json={'id':'expired-task','status':'expired'})
    )
    worker=Worker();worker.halt=NoWait()
    with pytest.raises(ValueError,match='任务已过期'):
        worker.execute(item)


@pytest.mark.parametrize('status,phrase',[(401,'鉴权失败'),(403,'服务拒绝访问'),(429,'服务限流'),(500,'服务暂时异常')])
def test_ark_http_errors_are_clear_in_chinese(status,phrase):
    with pytest.raises(ValueError,match=phrase):
        checked(httpx.Response(status,json={'error':{'message':'upstream detail'}}))


def test_model_catalog_is_grouped_and_custom_endpoints_keep_configured_kind(monkeypatch):
    p=provider()
    p['models']['video']='ep-custom-video'
    original=httpx.Client
    def handle(request):
        assert request.method=='GET' and request.url.path=='/api/v3/models'
        return httpx.Response(200,json={'data':[
            {'id':'doubao-seed-2-0-pro','name':'Doubao'},
            {'id':'doubao-seedream-4-5-251128','name':'Seedream 4.5'},
            {'id':'doubao-seedance-1-5-pro-251215','name':'Seedance 1.5'},
            {'id':'ep-custom-video','name':'私有接入点'},
            {'id':'doubao-embedding-large','name':'Embedding'},
        ]})
    mock_egress(monkeypatch,handle)
    models=ark.list_models(p)
    assert {m['id']:m['kind'] for m in models}=={
        'doubao-seed-2-0-pro':'text',
        'doubao-seedream-4-5-251128':'image',
        'doubao-seedance-1-5-pro-251215':'video',
        'ep-custom-video':'video',
    }
    assert models[0]['id']=='ep-custom-video'
    assert ark.check_configured_model(p,'video')['status']=='listed'


def test_unlisted_custom_model_is_reported_without_generation(monkeypatch):
    p=provider();p['models']['image']='ep-not-returned'
    original=httpx.Client
    mock_egress(monkeypatch,
        lambda request:httpx.Response(200,json={'data':[]})
    )
    result=ark.check_configured_model(p,'image')
    assert result['status']=='unlisted'
    assert result['model']=='ep-not-returned'
