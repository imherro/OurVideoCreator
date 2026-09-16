"""P4 actual API -> PG -> separate Worker -> loopback HTTP, no paid providers."""
import io
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

from backend import store as s
from tests.platform_model_helpers import admin, create_provider, create_model, CANARY, publish_test_model
from tests.test_p1_processes import stop, wait_until


def project(admin):
    response=admin.post('/api/projects',json={'name':'P4 controlled execution'})
    assert response.status_code==200,response.text
    return response.json()


def submit(admin,pid,model_id,**changes):
    return admin.post(f'/api/projects/{pid}/jobs',json={
        'node_id':'p4-node','kind':'text','submission_id':s.uid('p4-submit-'),
        'input':{'model_id':model_id,'prompt':'Synthetic test prompt'},**changes})


def test_real_job_snapshot_and_retired_paths(admin):
    provider=create_provider(admin)
    model=create_model(admin,provider)
    pid=project(admin)['id']
    response=submit(admin,pid,model['id'])
    assert response.status_code==200,response.text
    job=response.json()
    with s.db() as c:
        private=c.execute('SELECT * FROM job_private WHERE job_id=%s',(job['id'],)).fetchone()
        assert json.loads(private['provider'])=={}
        assert json.loads(private['parameters'])=={'max_tokens':100}
        assert private['credential_version_id']==provider['credential_version_id']
        assert CANARY not in str(private)
    assert CANARY not in admin.get(f"/api/jobs/{job['id']}").text
    assert 'private-upstream-test-id' not in admin.get('/api/settings').text
    assert 'models.example.test' not in admin.get('/api/settings').text
    for suffix in ('verify','test'):
        assert admin.post(f"/api/providers/{provider['id']}/{suffix}").status_code==410
    assert admin.get(f"/api/providers/{provider['id']}/models").status_code==410
    assert admin.put('/api/settings',json={'providers':[]}).status_code==410
    assert admin.post(f"/api/jobs/{job['id']}/cancel").status_code==200


@pytest.mark.parametrize('injection',[
    {'provider':'legacy'}, {'model':'upstream'}, {'parameters':{'hidden':{'apiKey':'not-secret'}}},
    {'extra':[{'headers':{'Authorization':'not-secret'}}]}, {'nested':{'url':'http://127.0.0.1/'}},
])
def test_single_and_document_nested_injection_rejected_without_job(admin,injection):
    provider=create_provider(admin);model=create_model(admin,provider);p=project(admin)
    before=admin.get(f"/api/projects/{p['id']}/jobs").json()
    response=submit(admin,p['id'],model['id'],input={'model_id':model['id'],'prompt':'test',**injection})
    assert response.status_code==400,response.text
    document={**p['document'],'nodes':[{'id':'inject','data':{'kind':'text','model_id':model['id'],**injection}}]}
    response=admin.put(f"/api/projects/{p['id']}",json={'name':p['name'],'revision':p['revision'],
        'production_revision':p['production_revision'],'document':document})
    assert response.status_code==400,response.text
    assert admin.get(f"/api/projects/{p['id']}/jobs").json()==before


def test_capability_kind_parameters_and_foreign_dependencies_rejected(admin):
    model=create_model(admin,create_provider(admin));p=project(admin)
    for changes in (
        {'kind':'image'},
        {'input':{'model_id':model['id'],'prompt':'test','parameters':{'max_tokens':201}}},
        {'input':{'model_id':model['id'],'prompt':'test','asset_ids':['not-owned']}},
        {'input':{'model_id':model['id'],'prompt':'test','upstream_job_ids':['foreign-job']}},
        {'input':{'model_id':model['id'],'prompt':'test','parameters':[]}},
    ):
        response=submit(admin,p['id'],model['id'],**changes)
        assert response.status_code==400,response.text
    assert admin.get(f"/api/projects/{p['id']}/jobs").json()==[]


def test_batch_late_invalid_parameters_rolls_back_all_jobs(admin):
    model=create_model(admin,create_provider(admin));p=project(admin)
    document={**p['document'],'nodes':[
        {'id':'first','position':{'x':0,'y':0},'data':{'kind':'text','prompt':'first','model_id':model['id']}},
        {'id':'second','position':{'x':10,'y':10},'data':{'kind':'text','prompt':'second','model_id':model['id'],
                                                    'parameters':{'max_tokens':201}}},
    ],'edges':[]}
    saved=admin.put(f"/api/projects/{p['id']}",json={'name':p['name'],'revision':p['revision'],
        'production_revision':p['production_revision'],'document':document})
    assert saved.status_code==200,saved.text
    valid=admin.post(f"/api/projects/{p['id']}/run",json={'submission_id':s.uid('batch-valid-'),
                                                     'node_ids':['first'],'exact':True})
    assert valid.status_code==200,valid.text
    assert valid.json()['count']==1
    existing=valid.json()['job_ids']
    for jid in existing: assert admin.post('/api/jobs/'+jid+'/cancel').status_code==200
    response=admin.post(f"/api/projects/{p['id']}/run",json={'submission_id':s.uid('batch-'),
                                                         'node_ids':['first','second'],'exact':True})
    assert response.status_code==400,response.text
    assert [job['id'] for job in admin.get(f"/api/projects/{p['id']}/jobs").json()]==existing


def test_audio_batch_late_error_is_atomic(admin):
    model=publish_test_model(admin,'audio-batch-model',kind='audio',provider_type='volcengine_speech',
        rules={'voice_type':{'type':'string','enum':['synthetic-voice']}},defaults={'voice_type':'synthetic-voice'})
    p=project(admin)
    def item(node,voice):
        return {'node_id':node,'kind':'audio','submission_id':s.uid('audio-batch-'),
                'input':{'model_id':model['id'],'prompt':'测试对白','parameters':{'voice_type':voice}}}
    endpoint=f"/api/projects/{p['id']}/audio-jobs"
    rejected=admin.post(endpoint,json={'jobs':[item('a','synthetic-voice'),item('b','unpublished-voice')]})
    assert rejected.status_code==400,rejected.text
    assert admin.get(f"/api/projects/{p['id']}/jobs").json()==[]
    accepted=admin.post(endpoint,json={'jobs':[item('a','synthetic-voice'),item('b','synthetic-voice')]})
    assert accepted.status_code==200,accepted.text
    assert len(admin.get(f"/api/projects/{p['id']}/jobs").json())==2


def test_shot_timing_uses_canonical_duration_and_published_rules(admin):
    from backend import platform_models
    model=publish_test_model(admin,'frame-model',kind='video',provider_type='maestro',
        capabilities={'fps':24,'min_frames':124,'frame_step':17,'max_frames':345},
        rules={'frames':{'type':'integer','min':124,'max':345}},defaults={'frames':124})
    p=project(admin)
    p['document']['shots']=[{'id':'shot','videoNode':'p4-node','duration':8}]
    saved=admin.put(f"/api/projects/{p['id']}",json={'name':p['name'],'revision':p['revision'],
        'production_revision':p['production_revision'],'document':p['document']})
    assert saved.status_code==200,saved.text
    response=submit(admin,p['id'],model['id'],kind='video',input={
        'model_id':model['id'],'prompt':'镜头移动','parameters':{'frames':124},
        'model_capabilities':{'fps':1000}})
    assert response.status_code==200,response.text
    with s.db() as c:
        frozen=platform_models.load_job_provider(c,response.json()['id'])
    assert frozen['job_parameters']['frames']==192


def test_separate_worker_text_and_async_image_loopback_chain(admin,monkeypatch,tmp_path):
    counts={'text':0,'submit':0,'poll':0,'download':0,'wrong_auth':0}
    png=io.BytesIO();Image.new('RGB',(8,8),'blue').save(png,format='PNG')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,value,mime='application/json'):
            data=value if isinstance(value,bytes) else json.dumps(value).encode()
            self.send_response(200);self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def authenticated(self):
            if self.headers.get('Authorization')!='Bearer '+CANARY:counts['wrong_auth']+=1
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))) or '{}')
            self.authenticated()
            if self.path=='/v1/chat/completions':
                counts['text']+=1
                assert body['model']=='private-upstream-test-id'
                assert body['max_tokens']==100
                content='Controlled text '+CANARY
                self.reply(('data: '+json.dumps({'choices':[{'delta':{'content':content}}]})+
                            '\n\ndata: [DONE]\n\n').encode(),'text/event-stream')
            elif self.path=='/v1/models/test/image/predictions':
                counts['submit']+=1
                self.reply({'id':'p4-remote-image'})
            else:self.send_error(404)
        def do_GET(self):
            if self.path=='/v1/predictions/p4-remote-image':
                self.authenticated();counts['poll']+=1
                self.reply({'id':'p4-remote-image','status':'succeeded',
                            'output':f'http://127.0.0.1:{self.server.server_port}/result.png'})
            elif self.path=='/result.png':
                counts['download']+=1
                if self.headers.get('Authorization'):counts['wrong_auth']+=1
                self.reply(png.getvalue(),'image/png')
            else:self.send_error(404)

    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setenv('OVC_PROVIDER_EGRESS_EXCEPTIONS',json.dumps([{
        'scheme':'http','host':'127.0.0.1','ip':'127.0.0.1','port':server.server_port}]))
    worker=None
    try:
        base=f'http://127.0.0.1:{server.server_port}/v1'
        text_model=create_model(admin,create_provider(admin,config={'type':'openai','url':base}))
        media_provider=create_provider(admin,config={'type':'replicate','url':base})
        response=admin.post('/api/admin/models',json={
            'revision':0,'provider_id':media_provider['id'],'kind':'image','published':True,'enabled':True,
            'definition':{'name':'P4 async image','upstream_model':'test/image',
                          'capabilities':{},'defaults':{},'rules':{}}})
        assert response.status_code==200,response.text
        p=project(admin)
        first=submit(admin,p['id'],text_model['id'])
        second=submit(admin,p['id'],response.json()['id'],kind='image')
        assert first.status_code==second.status_code==200
        jobs=[first.json()['id'],second.json()['id']]
        stdout_path,stderr_path=tmp_path/'worker.stdout.log',tmp_path/'worker.stderr.log'
        with stdout_path.open('w',encoding='utf-8') as out,stderr_path.open('w',encoding='utf-8') as err:
            worker=subprocess.Popen([sys.executable,'-m','backend.worker_cli','--concurrency','1'],
                cwd=Path(__file__).resolve().parents[1],env={**os.environ,'PYTHONUTF8':'1'},
                stdout=out,stderr=err,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        def completed():
            rows=[admin.get('/api/jobs/'+jid).json() for jid in jobs]
            return rows if all(row['status'] in ('succeeded','failed','interrupted') for row in rows) else None
        results=wait_until(completed,'P4 Worker did not finish',timeout=25)
        assert [row['status'] for row in results]==['succeeded','succeeded'],[row.get('error') for row in results]
        assert results[0]['result']['text']=='Controlled text [REDACTED]'
        image=results[1]['result']['assets'][0]
        assert admin.get(image['url']).content==png.getvalue()
        assert counts=={'text':1,'submit':1,'poll':1,'download':1,'wrong_auth':0}
        # Retained non-inference export runs in the same independent Worker.
        # It consumes only the generated asset, never platform credentials.
        exported=admin.post(f"/api/projects/{p['id']}/jobs",json={
            'node_id':'p4-export','kind':'export','submission_id':s.uid('p4-export-'),
            'input':{'timeline':[{'asset_id':image['id'],'duration':.5,'start':0}],
                     'resolution':'128x128'}})
        assert exported.status_code==200,exported.text
        def export_completed():
            item=admin.get('/api/jobs/'+exported.json()['id']).json()
            return item if item['status'] in ('succeeded','failed','interrupted') else None
        export_result=wait_until(export_completed,'P4 non-inference export did not finish',timeout=30)
        assert export_result['status']=='succeeded',export_result.get('error')
        export_asset=export_result['result']['assets'][0]
        assert export_asset['kind']=='video'
        assert CANARY.encode() not in admin.get(export_asset['url']).content
        assert CANARY not in json.dumps(export_result)
        for endpoint in (f"/api/projects/{p['id']}",f"/api/projects/{p['id']}/revisions"):
            response=admin.get(endpoint)
            assert response.status_code==200
            assert CANARY not in response.text
        assert counts=={'text':1,'submit':1,'poll':1,'download':1,'wrong_auth':0}
        assert CANARY not in json.dumps(results)
        with s.db() as c:
            for table in ('jobs','job_private','assets','events','audit_events'):
                # Synthetic canary is never printed, including on assertion failure.
                rows=c.execute('SELECT * FROM '+table).fetchall()
                assert not any(CANARY in str(row) for row in rows),table
        assert CANARY not in stdout_path.read_text(encoding='utf-8')
        assert CANARY not in stderr_path.read_text(encoding='utf-8')
    finally:
        stop(worker);server.shutdown();server.server_close();thread.join(timeout=3)
