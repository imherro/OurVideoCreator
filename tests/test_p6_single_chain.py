"""Ordinary editor -> TestClient -> PG -> independent Worker -> loopback fake.

No browser/real paid API claims. No execution/quota primitives are used.
"""
import io
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

from PIL import Image
from backend import store as s
from tests.test_p5_object_transactions import team,admin,clients,clear_auth_rate_limits,create,url
from tests.platform_model_helpers import publish_test_model
from tests.collaboration_helpers import create_node
from tests.test_p1_processes import stop,wait_until


def test_editor_single_worker_idempotent_text_async_media_and_export(team,monkeypatch,tmp_path):
    ledger={'text':0,'submit':0,'poll':0,'download':0}
    png=io.BytesIO();Image.new('RGB',(16,16),'blue').save(png,format='PNG')
    class Fake(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,data,mime='application/json'):
            data=data if isinstance(data,bytes) else json.dumps(data).encode()
            self.send_response(200);self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length',0)))
            if self.path=='/v1/chat/completions':
                ledger['text']+=1
                data='data: '+json.dumps({'choices':[{'delta':{'content':'single-worker candidate'}}]})+'\n\ndata: [DONE]\n\n'
                self.reply(data.encode(),'text/event-stream')
            elif self.path=='/v1/models/test/image/predictions':
                ledger['submit']+=1;self.reply({'id':'single-media'})
            else:self.send_error(404)
        def do_GET(self):
            if self.path=='/v1/predictions/single-media':
                ledger['poll']+=1
                self.reply({'id':'single-media','status':'succeeded','output':f'http://127.0.0.1:{self.server.server_port}/result.png'})
            elif self.path=='/result.png':
                ledger['download']+=1;assert not self.headers.get('Authorization')
                self.reply(png.getvalue(),'image/png')
            else:self.send_error(404)
    server=ThreadingHTTPServer(('127.0.0.1',0),Fake)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setenv('OVC_PROVIDER_EGRESS_EXCEPTIONS',json.dumps([{
        'scheme':'http','host':'127.0.0.1','ip':'127.0.0.1','port':server.server_port}]))
    worker=None
    try:
        actor=team['a'];pid=team['pid'];endpoint='/api/projects/'+pid+'/jobs'
        models={}
        for kind,provider in [('text','openai'),('image','replicate')]:
            mid=s.uid('single-model-');models[kind]=mid
            publish_test_model(team['admin'],mid,kind=kind,provider_type=provider,
                upstream_model='test/image' if kind=='image' else 'test-text',
                url=f'http://127.0.0.1:{server.server_port}/v1')
            create_node(actor,pid,'single-'+kind,kind)
        create(team,kind='timeline')
        before=actor.get(url(team)).json()
        bodies=[{'node_id':'single-'+kind,'kind':kind,'submission_id':s.uid('single-'),
            'input':{'model_id':mid,'prompt':'preserve human content'}} for kind,mid in models.items()]
        jobs=[]
        for body in bodies:
            barrier=threading.Barrier(3)
            def submit():
                barrier.wait(10)
                return actor.post(endpoint,json=body)
            with ThreadPoolExecutor(max_workers=3) as pool:
                responses=list(pool.map(lambda _:submit(),range(3)))
            assert all(r.status_code==200 for r in responses),[r.text for r in responses]
            ids={r.json()['id'] for r in responses};assert len(ids)==1
            jobs.append(ids.pop())
        with s.db() as c:
            assert c.execute('SELECT count(*) n FROM jobs WHERE project_id=%s',(pid,)).fetchone()['n']==2
            assert c.execute('SELECT count(*) n FROM job_reservations WHERE job_id=ANY(%s)',(jobs,)).fetchone()['n']==0
        with (tmp_path/'worker.log').open('w',encoding='utf-8') as stream:
            worker=subprocess.Popen([sys.executable,'-m','backend.worker_cli','--concurrency','1'],
                cwd=Path(__file__).resolve().parents[1],env={**os.environ,'PYTHONUTF8':'1'},
                stdout=stream,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        def completed(ids):
            rows=[actor.get('/api/jobs/'+jid).json() for jid in ids]
            return rows if all(r['status'] in ('succeeded','failed','interrupted','cancelled') for r in rows) else None
        result=wait_until(lambda:completed(jobs),'single Worker did not finish',timeout=40)
        assert [r['status'] for r in result]==['succeeded','succeeded'],[r.get('error') for r in result]
        assert result[0]['result']['text']=='single-worker candidate'
        asset=result[1]['result']['assets'][0]
        assert actor.get(asset['url']).content==png.getvalue()
        assert actor.get(url(team)).json()==before
        for jid in jobs:
            assert actor.get('/api/projects/'+pid+'/candidates/'+jid).status_code==200
        for body,jid in zip(bodies,jobs):
            replay=actor.post(endpoint,json=body)
            assert replay.status_code==200 and replay.json()['id']==jid
        sent=actor.post(endpoint,json={'node_id':'single-export','kind':'export','submission_id':s.uid('single-export-'),
            'input':{'timeline':[{'asset_id':asset['id'],'duration':.3,'start':0}],'resolution':'128x128'}})
        assert sent.status_code==200,sent.text
        exported=wait_until(lambda:completed([sent.json()['id']]),'export did not finish',timeout=40)[0]
        assert exported['status']=='succeeded',exported.get('error')
        output=exported['result']['assets'][0]
        assert actor.get(output['url']).status_code==200
        assert not list(s.DATA.glob(sent.json()['id']+'-a*'))
        assert ledger=={'text':1,'submit':1,'poll':1,'download':1}
        print('SINGLE-01 ordinary editor / independent Worker ledger:',ledger)
    finally:
        stop(worker);server.shutdown();server.server_close();thread.join(5)
