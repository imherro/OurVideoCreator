"""Explicit disposable P4 browser fixture; no model/provider pre-seeding.

Run as a module with OVC_TEST_ADMIN_URL pointing at a dedicated local PG.
Leaves its own database/media/logs for review, never touches existing services.
The synthetic credential below is not a real service credential.
"""
from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography.fernet import Fernet
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CANARY = 'p4-ui-only-synthetic-canary-62ac721d'


def main():
    from tests.postgres_test_db import create_isolated_database
    folder = Path(tempfile.mkdtemp(prefix='ovc-p4-browser-'))
    os.environ.update(MVC_DATA_DIR=str(folder/'data'), PYTHONUTF8='1',
                      OVC_PROVIDER_MASTER_KEY=Fernet.generate_key().decode(),
                      OVC_PROVIDER_MASTER_KEY_ID='p4-browser-isolated',
                      NO_PROXY='127.0.0.1,127.0.0.2,localhost')
    database, _ = create_isolated_database(ROOT)
    png = io.BytesIO()
    Image.new('RGB', (256, 144), '#295779').save(png, format='PNG')
    counts = {'text': 0, 'submit': 0, 'poll': 0, 'download': 0, 'wrong_auth': 0}
    log_lock = threading.Lock()

    def record(value):
        with log_lock, (folder/'fake-calls.jsonl').open('a', encoding='utf-8') as out:
            out.write(json.dumps({'utc': datetime.now(timezone.utc).isoformat(), **value})+'\n')
        (folder/'counts.json').write_text(json.dumps(counts), encoding='utf-8')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def reply(self, data, mime='application/json'):
            raw = data if isinstance(data, bytes) else json.dumps(data).encode()
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers(); self.wfile.write(raw)
        def authorized(self):
            if self.headers.get('Authorization') != 'Bearer '+CANARY:
                counts['wrong_auth'] += 1
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or '{}')
            self.authorized()
            if self.path == '/v1/chat/completions':
                counts['text'] += 1
                record({'method': 'POST', 'path': self.path, 'account': 'UI-A', 'status': 200})
                content = 'P4 浏览器文本闭环成功。'+CANARY
                self.reply(('data: '+json.dumps({'choices':[{'delta':{'content':content}}]})+
                            '\n\ndata: [DONE]\n\n').encode(), 'text/event-stream')
            elif self.path == '/v1/models/test/image/predictions':
                counts['submit'] += 1
                record({'method':'POST', 'path':self.path, 'account':'UI-A', 'status':200})
                self.reply({'id':'p4-ui-image-'+str(counts['submit'])})
            else: self.send_error(404)
        def do_GET(self):
            if self.path.startswith('/v1/predictions/p4-ui-image-'):
                self.authorized(); counts['poll'] += 1
                record({'method':'GET', 'path':self.path, 'account':'UI-A', 'status':200})
                self.reply({'status':'succeeded', 'output':f'http://127.0.0.1:{self.server.server_port}/result.png'})
            elif self.path == '/result.png':
                counts['download'] += 1
                if self.headers.get('Authorization'): counts['wrong_auth'] += 1
                record({'method':'GET', 'path':self.path, 'account':'anonymous', 'status':200})
                self.reply(png.getvalue(), 'image/png')
            else: self.send_error(404)

    fake = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    record({'event':'started-no-calls'})
    os.environ['OVC_PROVIDER_EGRESS_EXCEPTIONS'] = json.dumps([{
        'scheme':'http', 'host':'127.0.0.1', 'ip':'127.0.0.1', 'port':fake.server_port}])
    from fastapi.testclient import TestClient
    from backend.app import app
    from backend import store as s, identity
    from tests.auth_helpers import login_admin, ADMIN_PASSWORD
    with TestClient(app) as client:
        admin = login_admin(client)
        p = client.post('/api/projects', json={'name':'P4 UI acceptance'}).json()
        now = time.time()
        with s.db() as c:
            uid = s.uid('p4-ui-manager-')
            c.execute("""INSERT INTO users(id,phone,nickname,password_hash,platform_role,is_active,created,updated)
                VALUES(%s,'+8613800000001','P4 UI Manager',%s,'user',TRUE,%s,%s)""",
                (uid, identity.hash_password(ADMIN_PASSWORD), now, now))
            c.execute("INSERT INTO workspace_members(workspace_id,user_id,role,created) VALUES(%s,%s,'member',%s)",
                      (admin['workspace_id'], uid, now))
            c.execute("INSERT INTO production_members(production_id,user_id,role,created) VALUES(%s,%s,'manager',%s)",
                      (p['production_id'], uid, now))
        doc = p['document']
        doc.update(nodes=[{'id':kind+'-ui', 'type':'media', 'position':{'x':i*430,'y':100},
                           'data':{'kind':kind,'label':'P4 '+kind+' UI','prompt':'合成验收内容','parameters':{}}}
                          for i,kind in enumerate(('text','image'))], edges=[])
        saved = client.put('/api/projects/'+p['id'], json={
            'name':p['name'], 'revision':p['revision'], 'production_revision':p['production_revision'], 'document':doc})
        assert saved.status_code == 200, saved.text
        assert client.get('/api/models').json()['models'] == []
    with socket.socket() as sock:
        sock.bind(('127.0.0.2',0)); port = sock.getsockname()[1]
    children=[]
    for name,args in (
        ('web',['-m','uvicorn','backend.app:app','--host','127.0.0.2','--port',str(port)]),
        ('worker',['-m','backend.worker_cli','--concurrency','1']),
    ):
        with (folder/(name+'.stdout.log')).open('w',encoding='utf-8') as out, (folder/(name+'.stderr.log')).open('w',encoding='utf-8') as err:
            children.append(subprocess.Popen([sys.executable,*args],cwd=ROOT,env=os.environ.copy(),
                stdout=out,stderr=err,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
    manifest={'utc':datetime.now(timezone.utc).isoformat(), 'directory':str(folder), 'database_name':database,
              'web_url':f'http://127.0.0.2:{port}', 'fake_base':f'http://127.0.0.1:{fake.server_port}/v1',
              'pids':{'harness':os.getpid(),'web':children[0].pid,'worker':children[1].pid},
              'project_id':p['id'], 'production_id':p['production_id'], 'ordinary_user_id':uid,
              'preseeded':'synthetic accounts/team/project/nodes only; zero providers/models'}
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(manifest),flush=True)
    # Stop only the exact child processes created here. Preserve evidence/DB.
    try:
        while not (folder/'stop').exists(): time.sleep(1)
    finally:
        from tests.test_p1_processes import stop
        for child in reversed(children): stop(child)
        fake.shutdown(); fake.server_close()


if __name__ == '__main__': main()
