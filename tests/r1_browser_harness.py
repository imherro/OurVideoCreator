"""Isolated five-role UI fixture. No real keys, provider models, or worker."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import socket
import tempfile


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=7886)
    parser.add_argument('--ui',type=Path,required=True)
    args=parser.parse_args()
    if not (args.ui/'index.html').is_file():raise RuntimeError('Build the staged UI first')
    # Refuse an occupied listener before creating fixtures.
    with socket.socket() as listener:listener.bind(('127.0.0.1',args.port))
    original=socket.socket.connect
    def guarded(instance,address):
        if isinstance(address,tuple):
            host=str(address[0]).split('%',1)[0]
            if host!='localhost' and not ipaddress.ip_address(host).is_loopback:
                raise RuntimeError('R1 fixture cannot access external providers')
        return original(instance,address)
    socket.socket.connect=guarded
    from cryptography.fernet import Fernet
    os.environ.update(MVC_DATA_DIR=tempfile.mkdtemp(prefix='ovc-r1-ui-'),
                      OVC_PROVIDER_MASTER_KEY=Fernet.generate_key().decode(),
                      OVC_PROVIDER_MASTER_KEY_ID='r1-ui-only')
    from tests.postgres_test_db import create_isolated_database
    database,_=create_isolated_database(Path(__file__).resolve().parents[1])
    from fastapi.testclient import TestClient
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    from backend.app import app
    from backend import identity
    from tests.auth_helpers import login_admin
    def checked(response):
        if response.status_code>=400:raise RuntimeError(f'Fixture API failure {response.status_code}: {response.text}')
        return response.json()
    people=[]
    with TestClient(app) as admin:
        owner=login_admin(admin)
        project=checked(admin.post('/api/projects',json={'name':'R1 五角色隔离样片','creation_mode':'direct','five_role_workflow':True}))
        pid=project['production_id'];base=f'/api/productions/{pid}/workflow'
        for index,(role,name) in enumerate([('writer','编剧小林'),('artist','资产小周'),('generator','抽卡小陈'),('editor','剪辑小李')],1):
            invitation=checked(admin.post('/api/admin/invitations',json={'expires_hours':48}))
            with TestClient(app) as member:
                user=checked(member.post('/api/auth/register',json={'invitation_token':invitation['token'],
                    'phone':f'+861390000010{index}','nickname':name,'password':'R1-isolated-browser-only!'}))['user']
                member.headers.update({'X-CSRF-Token':member.cookies.get(identity.CSRF_COOKIE)})
                checked(admin.put(f"/api/workspaces/{owner['workspace_id']}/members/{user['id']}",json={'role':'member'}))
                state=checked(admin.get(base))
                state=checked(admin.put(base+'/members/'+user['id'],json={'revision':state['config']['revision'],'roles':[role]}))
                if role=='writer':
                    source=checked(member.post(f'/api/productions/{pid}/sources',json={'title':'测试原著','type':'manual','metadata':{}}))
                    checked(member.post(f"/api/productions/{pid}/sources/{source['id']}/chapters",json={'title':'第一章：相遇','content':'雨夜，两名旅人在车站相遇。'}))
                people.append({'nickname':name,'role':role})
        assert checked(admin.get('/api/models'))['models']==[]
    # Serve only this staged build, leaving the live 7878 static directory untouched.
    app.router.routes[:]=[route for route in app.router.routes if getattr(route,'path','').startswith('/api')]
    def page():return FileResponse(args.ui/'index.html')
    for path in ('/workflow','/members','/admin'):
        app.add_api_route(path,page,methods=['GET'])
    app.mount('/',StaticFiles(directory=args.ui,html=True),name='r1-staged-ui')
    print(json.dumps({'url':f'http://127.0.0.1:{args.port}/','production_id':pid,
        'project_id':project['id'],'database':database,'members':people,'paid_calls':0},ensure_ascii=False),flush=True)
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=args.port,log_level='warning')


if __name__=='__main__':main()
