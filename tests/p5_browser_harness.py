"""Disposable P5 UI fixture using public registration/ACL/object APIs.

Two loopback hosts provide independent browser cookie jars against the same
isolated database. Never upgrades existing app databases or starts paid jobs.
The opt-in candidates mode uses only a controlled loopback HTTP fake.
"""
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
PASSWORD='P5-browser-isolated-only!'


def checked(response,status=200):
    assert response.status_code==status,response.text
    return response.json()


def main():
    business_sha = None
    if '--formal-sha' in sys.argv:
        from scripts.capture_p5_evidence import check_business
        business_sha = sys.argv[sys.argv.index('--formal-sha') + 1]
        check_business(business_sha)
    folder=Path(tempfile.mkdtemp(prefix='ovc-p5-browser-'))
    hosts=['127.0.0.5','127.0.0.6'] if '--owned-content' in sys.argv else ['127.0.0.3','127.0.0.4']
    if '--latest' in sys.argv:
        hosts=['127.0.0.7','127.0.0.8']
    candidate_mode = '--candidates' in sys.argv
    fake = None
    if candidate_mode:
        hosts=['127.0.0.9','127.0.0.10']
        from cryptography.fernet import Fernet
        os.environ.update(OVC_PROVIDER_MASTER_KEY=Fernet.generate_key().decode('ascii'),
                          OVC_PROVIDER_MASTER_KEY_ID='p5-browser-test')
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args): pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                record=json.dumps({
                    'utc':datetime.now(timezone.utc).isoformat(),'path':self.path,'payload':payload,
                })
                (folder/f'fake-received-{time.time_ns()}.json').write_text(record,encoding='utf-8')
                (folder/'fake-received.json').write_text(record,encoding='utf-8')
                while not (folder/'release-candidate').exists():
                    if (folder/'stop').exists():return
                    time.sleep(.1)
                content='P5 controlled late candidate result'
                data=('data: '+json.dumps({'choices':[{'delta':{'content':content}}]})+
                      '\n\ndata: [DONE]\n\n').encode()
                self.send_response(200);self.send_header('Content-Type','text/event-stream')
                self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        fake=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=fake.serve_forever,daemon=True).start()
        os.environ['OVC_PROVIDER_EGRESS_EXCEPTIONS']=json.dumps([{
            'scheme':'http','host':'127.0.0.1','ip':'127.0.0.1','port':fake.server_port}])
    if business_sha:
        hosts=['127.0.0.11','127.0.0.12']
    os.environ.update(MVC_DATA_DIR=str(folder/'data'),PYTHONUTF8='1',NO_PROXY=','.join([*hosts,'localhost']))
    from tests.postgres_test_db import create_isolated_database
    database,_=create_isolated_database(ROOT)
    from fastapi.testclient import TestClient
    from backend.app import app
    from backend import identity
    from tests.auth_helpers import login_admin
    members={};candidate={}
    with ExitStack() as stack:
        owner=stack.enter_context(TestClient(app));admin=login_admin(owner)
        project=checked(owner.post('/api/projects',json={'name':'P5 two editor UI'}))
        pid=project['id'];production=project['production_id']
        if candidate_mode:
            provider=checked(owner.post('/api/admin/model-providers',json={
                'revision':0,'name':'P5 loopback candidate only','enabled':True,'api_key':'',
                'config':{'type':'openai','url':f'http://127.0.0.1:{fake.server_port}/v1','auth_mode':'none'}}))
            model=checked(owner.post('/api/admin/models',json={
                'revision':0,'provider_id':provider['id'],'kind':'text','published':True,'enabled':True,
                'definition':{'name':'P5 controlled candidate','upstream_model':'p5-fake',
                              'capabilities':{},'defaults':{},'rules':{}}}))
        for index,(name,role) in enumerate([('A','editor'),('B','editor'),('Manager','manager'),('Viewer','viewer')],start=1):
            client=stack.enter_context(TestClient(app))
            invitation=checked(owner.post('/api/admin/invitations',json={'expires_hours':48}))
            phone=f'+861390000000{index}'
            user=checked(client.post('/api/auth/register',json={'invitation_token':invitation['token'],
                'phone':phone,'nickname':'P5 '+name,'password':PASSWORD}))['user']
            assert user['platform_role']=='user'
            client.headers.update({'X-CSRF-Token':client.cookies.get(identity.CSRF_COOKIE)})
            checked(owner.put(f"/api/workspaces/{admin['workspace_id']}/members/{user['id']}",json={'role':'member'}))
            checked(owner.put(f"/api/productions/{production}/members/{user['id']}",json={'role':role}))
            members[name]={'id':user['id'],'phone':phone,'role':role}
            if role=='editor':
                key='shot-'+name.lower()
                shot={'id':name,'uid':key,'duration':4,'scene':'测试场景','characters':[],
                    'action':'初始动作 '+name,'emotion':'平静','camera':'中景','audio':'',
                    'image_prompt':'测试静帧 '+name,'video_prompt':'测试运镜 '+name,
                    'imageNode':key+'-image','videoNode':key+'-video',
                    'pipeline':{'imageNodeId':key+'-image','videoNodeId':key+'-video'}}
                nodes=[{'id':key+'-'+kind,'type':'media','data':{'kind':kind,
                    'label':name+' '+kind,'prompt':shot[kind+'_prompt'],'parameters':{}}} for kind in ['image','video']]
                obj=checked(client.post(f'/api/projects/{pid}/objects',json={'kind':'shot','content':{'shot':shot,'nodes':nodes}}),201)
                members[name]['shot_object_id']=obj['id']
                if candidate_mode and name=='A':
                    target=checked(client.post(f'/api/projects/{pid}/objects',json={
                        'kind':'node','content':{'node':{'id':'p5-ui-candidate','type':'media',
                        'data':{'kind':'text','label':'P5 candidate target','text':'P5 initial v1',
                                'prompt':'Generate controlled candidate','model_id':model['id']}}}}),201)
                    job=checked(client.post(f'/api/projects/{pid}/jobs',json={
                        'node_id':'p5-ui-candidate','kind':'text','submission_id':'p5-browser-candidate',
                        'input':{'model_id':model['id'],'prompt':'Generate controlled candidate'}}))
                    candidate={'object_id':target['id'],'job_id':job['id'],'model_id':model['id']}
                if '--owned-content' in sys.argv:
                    source=checked(client.post(f'/api/productions/{production}/sources',json={'title':'P5 Source '+name,'type':'manual','metadata':{}}))
                    chapter=checked(client.post(f"/api/productions/{production}/sources/{source['id']}/chapters",json={
                        'title':'P5 Chapter '+name,'content':'Initial chapter '+name}))
                    members[name]['chapter_id']=chapter['id']
        if '--owned-content' in sys.argv:
            script=checked(owner.get(f'/api/productions/{production}/episode-scripts/1'))
            checked(owner.post(f'/api/productions/{production}/owned-content/script/{pid}/assign',json={
                'expected_revision':script['revision'],'assignment_epoch':script['assignment_epoch'],'assignee_id':members['A']['id']}))
        rows=checked(owner.get(f'/api/projects/{pid}/objects'))
        for row in rows:
            if row['kind'] in {'timeline','director'}:
                checked(owner.post(f"/api/projects/{pid}/objects/{row['id']}/assign",json={
                    'expected_revision':row['revision'],'assignment_epoch':row['assignment_epoch'],'assignee_id':members['A']['id']}))
        if not candidate_mode:assert checked(owner.get('/api/models'))['models']==[]
    children=[];urls=[]
    for host in hosts:
        with socket.socket() as sock:
            sock.bind((host,0));port=sock.getsockname()[1]
        name='web-'+host[-1]
        with (folder/(name+'.stdout.log')).open('w',encoding='utf-8') as out,(folder/(name+'.stderr.log')).open('w',encoding='utf-8') as err:
            child=subprocess.Popen([sys.executable,'-m','uvicorn','backend.app:app','--host',host,'--port',str(port)],
                cwd=ROOT,env=os.environ.copy(),stdout=out,stderr=err,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        children.append(child);urls.append(f'http://{host}:{port}')
    if candidate_mode:
        with (folder/'worker.stdout.log').open('w',encoding='utf-8') as out,(folder/'worker.stderr.log').open('w',encoding='utf-8') as err:
            worker=subprocess.Popen([sys.executable,'-m','backend.worker_cli','--concurrency','1'],
                cwd=ROOT,env=os.environ.copy(),stdout=out,stderr=err,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        children.append(worker)
    manifest={'utc':datetime.now(timezone.utc).isoformat(),'business_sha':business_sha,
        'directory':str(folder),'database_name':database,
        'urls':urls,'project_id':pid,'production_id':production,'members':members,
        'pids':{'harness':os.getpid(),'webs':[child.pid for child in children[:2]],
                'worker':children[2].pid if candidate_mode else None},'candidate':candidate,
        'seed':'public ordinary-user APIs; controlled loopback fake and one worker' if candidate_mode else
               'bootstrap owner only via test helper; ordinary users registered and authorized through public APIs; zero models/providers/worker'}
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(manifest),flush=True)
    try:
        while not (folder/'stop').exists():time.sleep(1)
    finally:
        from tests.test_p1_processes import stop
        for child in reversed(children):stop(child)
        if fake:fake.shutdown();fake.server_close()


if __name__=='__main__':main()
