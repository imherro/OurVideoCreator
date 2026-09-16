import io
import base64
import json
import httpx
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from backend.app import app
from backend import store as s
from backend.providers import common, volcengine_ark as ark
from backend.worker import Worker
from test_api import project
from tests.auth_helpers import login_admin


@pytest.fixture
def batch_authenticated():
    with TestClient(app) as client:
        login_admin(client)
        yield client


def _image(client,pid,name):
    stream=io.BytesIO()
    Image.new('RGB',(864,480),'#283040').save(stream,format='PNG')
    return client.post('/api/projects/'+pid+'/assets',files={'file':(name,stream.getvalue(),'image/png')}).json()


def _minimax_settings(client):
    client.put('/api/settings',json={'providers':[{
        'id':'hailuo','name':'Hailuo','type':'minimax','kind':'video',
        'url':'https://api.minimax.io/v1','model':'MiniMax-Hailuo-2.3','local':False
    }]})


def _ark_settings(client):
    client.put('/api/settings',json={'providers':[{
        'id':'ark','name':'火山方舟','type':'volcengine_ark','local':False,
        'url':'https://ark.example/api/v3','api_key':'secret',
        'models':{'text':'doubao','image':'seedream','video':'seedance'},
    }]})


def test_batch_carries_static_reference_asset_to_minimax(batch_authenticated):
    client=batch_authenticated;item=project(client);asset=_image(client,item['id'],'first.png');_minimax_settings(client)
    doc=item['document']
    doc['nodes']=[
        {'id':'reference','data':{'kind':'reference','assetId':asset['id']}},
        {'id':'video','data':{'kind':'video','provider':'hailuo','prompt':'镜头向前推进'}},
    ]
    doc['edges']=[{'id':'frame','source':'reference','target':'video'}]
    assert client.put('/api/projects/'+item['id'],json={'name':item['name'],'revision':item['revision'],'document':doc}).status_code==200
    result=client.post('/api/projects/'+item['id']+'/run',json={'submission_id':'static-frame-batch-001','allow_cloud':True})
    assert result.status_code==200,result.text
    jobs=client.get('/api/projects/'+item['id']+'/jobs').json()
    assert len(jobs)==1
    assert jobs[0]['input']['asset_ids']==[asset['id']]
    with s.db() as db:
        frozen=db.execute('SELECT provider FROM job_private WHERE job_id=%s',(jobs[0]['id'],)).fetchone()['provider']
    assert 'MiniMax-Hailuo-2.3' in frozen


def test_exact_video_batch_reuses_completed_image_without_rerunning_it(batch_authenticated):
    client=batch_authenticated;item=project(client);asset=_image(client,item['id'],'ready-frame.png');_minimax_settings(client)
    doc=item['document']
    doc['nodes']=[
        {'id':'image','data':{'kind':'image','provider':'missing-old-provider','prompt':'已经完成的首帧','assetId':asset['id']}},
        {'id':'video','data':{'kind':'video','provider':'hailuo','prompt':'镜头缓慢推进'}},
    ]
    doc['edges']=[{'id':'frame','source':'image','target':'video'}]
    assert client.put('/api/projects/'+item['id'],json={'name':item['name'],'revision':item['revision'],'document':doc}).status_code==200
    result=client.post('/api/projects/'+item['id']+'/run',json={
        'submission_id':'exact-video-batch-001','node_ids':['video'],'exact':True,'allow_cloud':True,
    })
    assert result.status_code==200,result.text
    assert result.json()['count']==1
    jobs=client.get('/api/projects/'+item['id']+'/jobs').json()
    assert [job['node_id'] for job in jobs]==['video']
    assert jobs[0]['input']['asset_ids']==[asset['id']]
    assert jobs[0]['input']['image_reference_sources']==[{'type':'asset','asset_id':asset['id']}]


def test_batch_rejects_multiple_minimax_frames_before_queueing(batch_authenticated):
    client=batch_authenticated;item=project(client);one=_image(client,item['id'],'one.png');two=_image(client,item['id'],'two.png');_minimax_settings(client)
    doc=item['document']
    doc['nodes']=[
        {'id':'one','data':{'kind':'reference','assetId':one['id']}},
        {'id':'two','data':{'kind':'reference','assetId':two['id']}},
        {'id':'video','data':{'kind':'video','provider':'hailuo','prompt':'镜头向前推进'}},
    ]
    doc['edges']=[{'id':'one-edge','source':'one','target':'video'},{'id':'two-edge','source':'two','target':'video'}]
    assert client.put('/api/projects/'+item['id'],json={'name':item['name'],'revision':item['revision'],'document':doc}).status_code==200
    result=client.post('/api/projects/'+item['id']+'/run',json={'submission_id':'many-frame-batch-001','allow_cloud':True})
    assert result.status_code==400
    assert '一张首帧' in result.text
    assert client.get('/api/projects/'+item['id']+'/jobs').json()==[]


def test_batch_seedream_keeps_canvas_reference_order_after_parent_finishes(batch_authenticated,monkeypatch):
    client=batch_authenticated;item=project(client);_ark_settings(client)
    generated=_image(client,item['id'],'generated.png')
    static=_image(client,item['id'],'static.png')
    manual=_image(client,item['id'],'manual.png')
    doc=item['document']
    doc['nodes']=[
        {'id':'generated-node','data':{'kind':'image','provider':'ark','prompt':'生成角色定妆图'}},
        {'id':'static-node','data':{'kind':'reference','assetId':static['id']}},
        {'id':'target','data':{'kind':'image','provider':'ark','prompt':'融合三张参考图','asset_ids':[manual['id']]}},
    ]
    doc['edges']=[
        {'id':'generated-first','source':'generated-node','target':'target'},
        {'id':'static-second','source':'static-node','target':'target'},
    ]
    saved=client.put('/api/projects/'+item['id'],json={'name':item['name'],'revision':item['revision'],'document':doc})
    assert saved.status_code==200,saved.text
    result=client.post('/api/projects/'+item['id']+'/run',json={'submission_id':'ordered-ark-batch-001','allow_cloud':True})
    assert result.status_code==200,result.text
    jobs={job['node_id']:job for job in client.get('/api/projects/'+item['id']+'/jobs').json()}
    parent,target=jobs['generated-node'],jobs['target']
    assert target['input']['image_reference_sources']==[
        {'type':'upstream_job','job_id':parent['id']},
        {'type':'asset','asset_id':static['id']},
        {'type':'asset','asset_id':manual['id']},
    ]
    with s.db() as db:
        db.execute("UPDATE jobs SET status='succeeded',result=%s WHERE id=%s",(
            s.dumps({'assets':[{'id':generated['id'],'kind':'image'}]}),parent['id']))
        db.execute("UPDATE jobs SET status='running' WHERE id=%s",(target['id'],))
    expected=[]
    for asset in (generated,static,manual):
        with s.db() as db:
            row=db.execute('SELECT path FROM assets WHERE id=%s',(asset['id'],)).fetchone()
        expected.append((s.ASSETS/row['path']).read_bytes())
    original=httpx.Client
    def handle(request):
        body=json.loads(request.read())
        assert [base64.b64decode(value.split(',',1)[1]) for value in body['image']]==expected
        return httpx.Response(200,json={'data':[{'url':'https://result.example/frame.png'}]})
    monkeypatch.setattr(ark.httpx,'Client',lambda **kw:original(**kw,transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(common,'download_result',lambda job,url,ext:{'id':'result','kind':'image'})
    assert Worker().execute(target)['assets'][0]['id']=='result'


def test_batch_seedance_allows_dynamic_first_frame_with_explicit_last_frame(batch_authenticated,monkeypatch):
    client=batch_authenticated;item=project(client);_ark_settings(client)
    monkeypatch.setattr(ark,'list_models',lambda provider:[{
        'id':'seedance','kind':'video','capabilities':{'image_reference':True,'end_frame':True},
    }])
    tail=_image(client,item['id'],'tail.png')
    doc=item['document']
    doc['nodes']=[
        {'id':'first','data':{'kind':'image','provider':'ark','prompt':'生成视频首帧'}},
        {'id':'video','data':{'kind':'video','provider':'ark','prompt':'生成连续转场','end_asset_id':tail['id']}},
    ]
    doc['edges']=[{'id':'first-frame','source':'first','target':'video'}]
    saved=client.put('/api/projects/'+item['id'],json={'name':item['name'],'revision':item['revision'],'document':doc})
    assert saved.status_code==200,saved.text
    result=client.post('/api/projects/'+item['id']+'/run',json={'submission_id':'ark-fl2v-batch-001','allow_cloud':True})
    assert result.status_code==200,result.text
    jobs={job['node_id']:job for job in client.get('/api/projects/'+item['id']+'/jobs').json()}
    assert jobs['video']['input']['image_reference_sources']==[
        {'type':'upstream_job','job_id':jobs['first']['id']},
    ]
    assert jobs['video']['input']['end_asset_id']==tail['id']


def test_batch_seedance_rejects_end_frame_when_selected_model_lacks_capability(batch_authenticated,monkeypatch):
    client=batch_authenticated;item=project(client);_ark_settings(client)
    first=_image(client,item['id'],'first.png')
    tail=_image(client,item['id'],'tail.png')
    catalog_calls=[]
    monkeypatch.setattr(ark,'list_models',lambda provider:catalog_calls.append(provider['id']) or [{
        'id':'seedance-no-tail','kind':'video',
        'capabilities':{'image_reference':True,'end_frame':False},
    }])
    doc=item['document']
    doc['nodes']=[
        {'id':'first','data':{'kind':'image','provider':'ark','prompt':'现有首帧','assetId':first['id']}},
        {'id':'video','data':{
            'kind':'video','provider':'ark','model':'seedance-no-tail',
            'prompt':'镜头向前推进','end_asset_id':tail['id'],
        }},
    ]
    doc['edges']=[{'id':'first-frame','source':'first','target':'video'}]
    saved=client.put('/api/projects/'+item['id'],json={'name':item['name'],'revision':item['revision'],'document':doc})
    assert saved.status_code==200,saved.text
    result=client.post('/api/projects/'+item['id']+'/run',json={
        'submission_id':'ark-no-tail-batch-001','node_ids':['video'],'exact':True,'allow_cloud':True,
    })
    assert result.status_code==400
    assert '不支持尾帧' in result.text
    assert catalog_calls==['ark']
    assert client.get('/api/projects/'+item['id']+'/jobs').json()==[]
