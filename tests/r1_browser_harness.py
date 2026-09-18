"""Isolated five-role UI fixture. No real keys, provider models, or worker."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import socket
import tempfile
import subprocess
import time


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=7886)
    parser.add_argument('--host',default='127.0.0.31',help='Distinct loopback host keeps test cookies away from the live app')
    parser.add_argument('--ui',type=Path,required=True)
    parser.add_argument('--reviews',action='store_true')
    parser.add_argument('--deliveries',action='store_true')
    parser.add_argument('--asset-candidates',action='store_true')
    args=parser.parse_args()
    args.reviews=args.reviews or args.deliveries or args.asset_candidates
    if not (args.ui/'index.html').is_file():raise RuntimeError('Build the staged UI first')
    # Refuse an occupied listener before creating fixtures.
    if not ipaddress.ip_address(args.host).is_loopback:raise RuntimeError('UI fixture must remain loopback-only')
    with socket.socket() as listener:listener.bind((args.host,args.port))
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
                    if args.reviews:
                        checked(admin.put(base+'/episodes/'+project['id'],json={'revision':state['config']['revision'],
                            'role':'writer','user_id':user['id']}))
                        script_path=f'/api/productions/{pid}/episode-scripts/1'
                        script=checked(member.get(script_path))
                        from backend.adaptation import SCRIPT_FIELDS
                        payload={key:script[key] for key in SCRIPT_FIELDS}
                        payload.update(revision=script['revision'],assignment_epoch=script['assignment_epoch'],
                            title='第一集：雨夜相遇',body='外景，车站，夜。\n小林：末班车还没来。\n小周把伞递给小林。')
                        script=checked(member.put(script_path,json=payload))
                        checked(member.post(script_path+'/review',json={'revision':script['revision'],'assignment_epoch':script['assignment_epoch']}))
                if role=='artist' and args.reviews:
                    asset=checked(member.post(f"/api/projects/{project['id']}/objects",json={'kind':'visual_card','content':{
                        'card':{'id':'review-hero','name':'小林 · 雨夜旅人','kind':'character','currentVersionId':'review-hero-v1','parentCardId':None,'status':'active'},
                        'versions':{'review-hero-v1':{'id':'review-hero-v1','cardId':'review-hero','version':1,'parentVersionId':None,'status':'draft',
                            'spec':{'description':'深蓝色外套，短发，旧帆布包。雨夜站在车站屋檐下。','attributes':[]},'invariants':[],'references':[],'createdAt':1,'provenance':{}}},'voice_profile':None}}))
                    checked(member.post(base+'/reviews/assets',json={'action':'submit','items':[
                        {key:asset[key] for key in ('id','revision','assignment_epoch')}]}))
                if role=='generator' and (args.deliveries or args.asset_candidates):
                    checked(admin.put(base+'/episodes/'+project['id'],json={'revision':state['config']['revision'],
                        'role':'generator','user_id':user['id'],'confirm_special':True}))
                    script_path=f'/api/productions/{pid}/episode-scripts/1'
                    script=checked(admin.get(script_path))
                    checked(admin.post(script_path+'/approve',json={key:script[key] for key in ('revision','assignment_epoch')}))
                    if args.deliveries:
                        from backend import store as s
                        aid=s.uid('asset-');media=s.asset_path(aid,'.mp4')
                        subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-f','lavfi','-i',
                            'color=c=blue:s=320x240:r=25:d=1','-c:v','libx264','-pix_fmt','yuv420p',str(media)],check=True)
                        with s.db() as c:
                            c.execute('''INSERT INTO assets(id,project_id,production_id,name,kind,mime,path,source,metadata,created,category)
                                VALUES(%s,%s,%s,'isolated-blue-clip.mp4','video','video/mp4',%s,'upload','{}',%s,'general')''',
                                (aid,project['id'],pid,media.name,time.time()))
                        objects_path=f"/api/projects/{project['id']}/objects"
                        checked(member.post(objects_path,json={'kind':'shot','content':{
                            'shot':{'id':'01','uid':'r3-shot','videoNode':'r3-video','dialogues':[{'id':'r3-dialogue','characterName':'小林','text':'末班车来了。'}]},
                            'nodes':[{'id':'r3-video','type':'media','data':{'kind':'video','assetId':aid}}]}}))
                        graph=next(row for row in checked(member.get(objects_path)) if row['kind']=='graph')
                        graph['content'].update(shotOrder=['r3-shot'],nodeOrder=['r3-video'])
                        checked(member.patch(objects_path+'/'+graph['id'],json={'expected_revision':graph['revision'],
                            'assignment_epoch':graph['assignment_epoch'],'content':graph['content']}))
                    if args.asset_candidates:
                        import pytest
                        from tests.test_p5_storyboard_candidates import storyboard
                        with pytest.MonkeyPatch.context() as patch:
                            storyboard({'admin':admin,'a':member,'pid':project['id'],'production':pid},patch)
                people.append({'nickname':name,'role':role})
        if not args.asset_candidates:assert checked(admin.get('/api/models'))['models']==[]
    # Serve only this staged build, leaving the live 7878 static directory untouched.
    app.router.routes[:]=[route for route in app.router.routes if getattr(route,'path','').startswith('/api')]
    def page():return FileResponse(args.ui/'index.html')
    for path in ('/workflow','/members','/admin'):
        app.add_api_route(path,page,methods=['GET'])
    app.mount('/',StaticFiles(directory=args.ui,html=True),name='r1-staged-ui')
    print(json.dumps({'url':f'http://{args.host}:{args.port}/','production_id':pid,
        'project_id':project['id'],'database':database,'members':people,'paid_calls':0},ensure_ascii=False),flush=True)
    import uvicorn
    uvicorn.run(app,host=args.host,port=args.port,log_level='warning')


if __name__=='__main__':main()
