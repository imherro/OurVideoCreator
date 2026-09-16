"""Actual loopback HTTP accounts/addresses exercise frozen identities and recovery."""
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image
from backend import store as s
from backend.worker import Worker
from tests.platform_model_helpers import admin, create_provider, CANARY
from tests.test_p4_submission_execution import project, submit


def test_rotation_disable_revoke_keep_original_remote_identity_over_real_http(admin, monkeypatch):
    calls=[]; wrong_auth=[]; workers={}; servers=[]; threads=[]
    png=io.BytesIO();Image.new('RGB',(8,8),'green').save(png,format='PNG')
    def launch(alias,secret):
        class Handler(BaseHTTPRequestHandler):
            serial=0
            def log_message(self,*args):pass
            def reply(self,data,mime='application/json'):
                data=data if isinstance(data,bytes) else json.dumps(data).encode()
                self.send_response(200);self.send_header('Content-Type',mime)
                self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def check(self):
                if self.headers.get('Authorization')!='Bearer '+secret:wrong_auth.append(alias)
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length',0)))
                self.check()
                if self.path.endswith('/cancel'):
                    calls.append((alias,'cancel',self.path));self.reply({});return
                assert self.path=='/v1/models/test/image/predictions'
                Handler.serial+=1;remote=f'{alias}-{Handler.serial}'
                calls.append((alias,'submit',remote))
                # Simulate a graceful Worker shutdown just after the provider
                # accepted a task. The real adapter persists the returned handle.
                workers[alias].halt.set()
                self.reply({'id':remote})
            def do_GET(self):
                if self.path=='/image.png':
                    if self.headers.get('Authorization'):wrong_auth.append('download')
                    calls.append((alias,'download','image'))
                    self.reply(png.getvalue(),'image/png');return
                self.check();calls.append((alias,'poll',self.path))
                assert self.path.startswith('/v1/predictions/'+alias+'-')
                self.reply({'status':'succeeded','output':f'http://127.0.0.1:{self.server.server_port}/image.png'})
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        servers.append(server);threads.append(thread)
        return f'http://127.0.0.1:{server.server_port}/v1'
    base_a=launch('A',CANARY);base_b=launch('B',CANARY+'-B')
    monkeypatch.setenv('OVC_PROVIDER_EGRESS_EXCEPTIONS',json.dumps([
        {'scheme':'http','host':'127.0.0.1','ip':'127.0.0.1','port':server.server_port} for server in servers]))
    try:
        provider=create_provider(admin,config={'type':'replicate','url':base_a})
        response=admin.post('/api/admin/models',json={'revision':0,'provider_id':provider['id'],
            'kind':'image','published':True,'enabled':True,'definition':{
                'name':'Rotation image','upstream_model':'test/image','capabilities':{},'defaults':{},'rules':{}}})
        assert response.status_code==200,response.text
        model=response.json();p=project(admin)
        def accepted(alias):
            response=submit(admin,p['id'],model['id'],kind='image')
            assert response.status_code==200,response.text
            job=response.json();s.job_update(job['id'],status='running')
            workers[alias]=Worker()
            with pytest.raises(InterruptedError):workers[alias].execute(job)
            s.job_update(job['id'],status='interrupted')
            stored=admin.get('/api/jobs/'+job['id']).json()
            assert stored['provider_job_id'].startswith(alias+'-')
            return stored
        old_poll,old_cancel,old_revoke=accepted('A'),accepted('A'),accepted('A')
        rotated=admin.put('/api/admin/model-providers/'+provider['id'],json={
            'revision':provider['revision'],'name':provider['name'],'enabled':True,'api_key':CANARY+'-B',
            'config':{'type':'replicate','url':base_b}})
        assert rotated.status_code==200,rotated.text
        replacement=rotated.json();new_remote=accepted('B')
        with s.db() as c:
            rows=c.execute('SELECT job_id,credential_version_id,config_version_id FROM job_private WHERE job_id IN (%s,%s)',
                (old_poll['id'],new_remote['id'])).fetchall()
        by_job={row['job_id']:row for row in rows}
        assert by_job[old_poll['id']]['credential_version_id']==provider['credential_version_id']
        assert by_job[new_remote['id']]['credential_version_id']==replacement['credential_version_id']
        assert by_job[old_poll['id']]['config_version_id']!=by_job[new_remote['id']]['config_version_id']
        # Existing A handles continue polling/cancelling A, never B.
        resumed=admin.post('/api/jobs/'+old_poll['id']+'/resume')
        assert resumed.status_code==200,resumed.text
        assert Worker().execute(resumed.json())['assets']
        assert admin.post('/api/jobs/'+old_cancel['id']+'/cancel').status_code==200
        before=len(calls)
        assert admin.post(f"/api/admin/model-providers/{provider['id']}/credentials/{provider['credential_version_id']}/revoke").status_code==200
        assert admin.post('/api/jobs/'+old_revoke['id']+'/resume').status_code==400
        with pytest.raises(ValueError,match='吊销'):Worker().execute(old_revoke)
        assert len(calls)==before
        # Disable stops accepted-but-not-submitted tasks as well as new intake,
        # but a B handle already accepted remotely is still queryable.
        queued=submit(admin,p['id'],model['id'],kind='image').json()
        current=next(row for row in admin.get('/api/admin/model-providers').json()['providers'] if row['id']==provider['id'])
        disabled=admin.put('/api/admin/model-providers/'+provider['id'],json={
            'revision':current['revision'],'name':current['name'],'enabled':False,'config':current['config']})
        assert disabled.status_code==200,disabled.text
        assert submit(admin,p['id'],model['id'],kind='image').status_code==400
        with pytest.raises(ValueError,match='停用'):Worker().execute(queued)
        assert len(calls)==before
        resumed=admin.post('/api/jobs/'+new_remote['id']+'/resume')
        assert resumed.status_code==200,resumed.text
        assert Worker().execute(resumed.json())['assets']
        assert [item[:2] for item in calls]==[
            ('A','submit'),('A','submit'),('A','submit'),('B','submit'),
            ('A','poll'),('A','download'),('A','cancel'),('B','poll'),('B','download')]
        assert wrong_auth==[]
        assert CANARY not in str(calls)
    finally:
        for server in servers:server.shutdown();server.server_close()
        for thread in threads:thread.join(timeout=5)
