import asyncio
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, Request, Response, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from . import store as s
from . import identity, platform_models, model_validation, provider_egress, collaboration, job_admission
from .instance_identity import describe as describe_instance
from .prompts import TEMPLATES
from .generation_policy import (default_model_pool, default_platform_policy,
    validate_generation_policy, validate_model_pool, validate_policy_in_pool)
from .project_schema import empty_film_bible, migrate_document, new_document
from .production_context import (
    SHARED_DOCUMENT_KEYS,
    compose_project_document,
    episode_document_from_document,
    new_production_context,
    normalize_production_context,
    production_context_from_document,
    read_project_state,
)

@asynccontextmanager
async def lifespan(app):
    s.init()
    yield

app = FastAPI(
    title='安影 AI 视频工作室', lifespan=lifespan,
    docs_url=None, redoc_url=None, openapi_url=None,
)
from .model_routes import router as model_router
app.include_router(model_router)
from .collaboration_routes import router as collaboration_router
app.include_router(collaboration_router)
from .owned_content_routes import router as owned_content_router
app.include_router(owned_content_router)
from .collaboration_actions import router as collaboration_actions_router
app.include_router(collaboration_actions_router)
from .collaboration_metadata import router as collaboration_metadata_router
app.include_router(collaboration_metadata_router)
from .job_candidates import router as job_candidates_router
app.include_router(job_candidates_router)
from .workflow_routes import router as workflow_router
app.include_router(workflow_router)
PUBLIC = {
    '/api/health', '/api/auth/status', '/api/auth/setup', '/api/auth/login',
    '/api/auth/register', '/api/auth/password-reset',
}

@app.middleware('http')
async def auth(request: Request, call_next):
    context_token = None
    if request.url.path.startswith('/api/'):
        # Cookie-authenticated mutations must originate from this deployment.
        origin = request.headers.get('origin')
        if request.method not in ('GET','HEAD','OPTIONS') and origin and urlparse(origin).netloc != request.headers.get('host'):
            return Response('跨站请求已拒绝',status_code=403)
        signed_provider_asset = request.method in ('GET','HEAD') and request.url.path.startswith('/api/provider-assets/')
        principal = identity.resolve_session(request)
        context_token = identity.set_current(principal)
        try:
            if request.url.path not in PUBLIC and not signed_provider_asset:
                if not principal:
                    raise HTTPException(401, '请登录工作室')
                if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                    identity.require_csrf(request, principal)
                identity.authorize_request(request, principal)
        except HTTPException as exc:
            if context_token is not None:
                identity.reset_current(context_token)
            return Response(s.dumps({'detail':exc.detail}),exc.status_code,media_type='application/json')
    try:
        result = await call_next(request)
    finally:
        if context_token is not None:
            identity.reset_current(context_token)
    result.headers['X-Content-Type-Options'] = 'nosniff'
    result.headers['Referrer-Policy'] = 'same-origin'
    if request.url.path.startswith('/api/'):
        result.headers['Cache-Control'] = 'no-store'
    return result

@app.exception_handler(ValueError)
async def value_error(request, exc):
    return Response(s.dumps({'detail':str(exc)}),400,media_type='application/json')

@app.get('/api/health')
def health():
    return {
        'status':'ok','app':'安影','version':'0.1.0','role':'web',
        'instance_id':describe_instance()['instance_id'],
    }

@app.get('/api/auth/status')
def auth_status(request: Request):
    principal = identity.resolve_session(request)
    with s.db() as c:
        configured=bool(c.execute("SELECT 1 FROM users WHERE platform_role='platform_admin' AND is_active LIMIT 1").fetchone())
        workspaces=[]
        if principal:
            workspaces=[dict(row) for row in c.execute(
                '''SELECT w.id,w.name,wm.role FROM workspaces w
                   JOIN workspace_members wm ON wm.workspace_id=w.id
                   WHERE wm.user_id=%s ORDER BY w.name,w.id''',(principal.user_id,),
            )]
    return {
        'configured':configured, 'authenticated':bool(principal), 'can_setup':False,
        'user': ({'id':principal.user_id,'nickname':principal.nickname,
                  'phone':principal.phone,'platform_role':principal.platform_role} if principal else None),
        'workspaces':workspaces,
    }

@app.post('/api/auth/setup')
def setup():
    raise HTTPException(410, '公开初始化已退役；请使用受保护的 bootstrap-admin CLI。')


class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid')


class LoginBody(StrictBody):
    phone: str = Field(min_length=5,max_length=32)
    password: str = Field(min_length=1,max_length=128)


class RegisterBody(StrictBody):
    invitation_token: str = Field(min_length=20,max_length=256)
    phone: str = Field(min_length=5,max_length=32)
    nickname: str = Field(min_length=1,max_length=80)
    password: str = Field(min_length=15,max_length=128)


class ResetPasswordBody(StrictBody):
    token: str = Field(min_length=20,max_length=256)
    password: str = Field(min_length=15,max_length=128)


@app.post('/api/auth/register')
def register(body:RegisterBody,request:Request,response:Response):
    phone=identity.normalize_phone(body.phone);nickname=body.nickname.strip()
    if not nickname:raise ValueError('昵称不能为空')
    now=time.time()
    invite_hash=identity.digest(body.invitation_token)
    ip_key='register:ip:'+identity.client_ip(request)
    invite_key='register:invite:'+invite_hash
    failure = None
    with s.db() as c:
        identity.rate_limit(c,[ip_key,invite_key],limit=8)
        invitation=c.execute('SELECT * FROM invitations WHERE token_hash=%s FOR UPDATE',(invite_hash,)).fetchone()
        if not invitation or invitation['revoked_at'] or invitation['consumed_at'] or invitation['expires']<=now:
            identity.record_failure(c,[ip_key,invite_key],limit=8)
            failure = HTTPException(400,'邀请码无效或已失效')
        else:
            encoded=identity.hash_password(body.password)
            user_id=s.uid('user-')
            try:
                c.execute('''INSERT INTO users(id,phone,nickname,password_hash,platform_role,is_active,created,updated)
                    VALUES(%s,%s,%s,%s,'user',TRUE,%s,%s)''',(user_id,phone,nickname,encoded,now,now))
            except Exception as exc:
                if getattr(exc,'sqlstate',None)=='23505':
                    raise HTTPException(409,'该手机号已注册') from exc
                raise
            changed=c.execute('''UPDATE invitations SET consumed_at=%s,consumed_by=%s
                WHERE id=%s AND consumed_at IS NULL AND revoked_at IS NULL RETURNING id''',
                (now,user_id,invitation['id'])).fetchone()
            if not changed:raise HTTPException(409,'邀请码已被使用')
            identity.audit(c,'user.register','user',user_id,actor_user_id=user_id,payload={'invitation_id':invitation['id']})
            # A successful invitation must not erase other clients' shared-IP history.
            identity.clear_rate_limit(c,[invite_key])
            identity.issue_session(c,response,request,user_id)
    if failure:
        raise failure
    return {'ok':True,'user':{'id':user_id,'nickname':nickname,'platform_role':'user'},'waiting_for_workspace':True}


@app.post('/api/auth/login')
def login(body:LoginBody,request:Request,response:Response):
    phone=identity.normalize_phone(body.phone)
    keys=['login:ip:'+identity.client_ip(request),'login:account:'+identity.digest(phone)]
    failure = None
    with s.db() as c:
        identity.rate_limit(c,keys)
        # The user row is the credential serialization boundary shared with
        # password reset and account deactivation. A verified old password
        # cannot issue a session after a reset has committed.
        user=c.execute('SELECT * FROM users WHERE phone=%s FOR UPDATE',(phone,)).fetchone()
        if not user or not user['is_active'] or not identity.verify_password(user['password_hash'],body.password):
            identity.record_failure(c,keys)
            failure = HTTPException(401,'手机号或密码不正确')
        else:
            # Clear only this account's failures. The IP bucket represents
            # attempts against every account sharing that address.
            identity.clear_rate_limit(c,[keys[1]])
            identity.issue_session(c,response,request,user['id'])
            identity.audit(c,'session.login','user',user['id'],actor_user_id=user['id'])
    if failure:
        raise failure
    return {'ok':True,'user':{'id':user['id'],'nickname':user['nickname'],'platform_role':user['platform_role']}}

@app.post('/api/auth/logout')
def logout(request:Request,response:Response):
    identity.clear_session(response,request)
    return {'ok':True}


@app.post('/api/auth/password-reset')
def consume_password_reset(body:ResetPasswordBody,request:Request,response:Response):
    token_hash=identity.digest(body.token)
    keys=['reset:ip:'+identity.client_ip(request),'reset:token:'+token_hash]
    failure = None
    with s.db() as c:
        identity.rate_limit(c,keys,limit=8)
        # Discover the lock root without locking the token, then always acquire
        # user -> token. Issuance uses the same order, avoiding a recovery-path
        # deadlock while still rechecking every token field under lock.
        hint=c.execute('SELECT id,user_id FROM password_reset_tokens WHERE token_hash=%s',(token_hash,)).fetchone()
        if not hint:
            identity.record_failure(c,keys,limit=8)
            failure = HTTPException(400,'重置链接无效或已失效')
        else:
            user=identity.lock_password_recovery_user(c,hint['user_id'])
            item=c.execute('SELECT * FROM password_reset_tokens WHERE id=%s FOR UPDATE',(hint['id'],)).fetchone()
            now=time.time()
            if not item or item['revoked_at'] or item['consumed_at'] or item['expires']<=now:
                identity.record_failure(c,keys,limit=8)
                failure = HTTPException(400,'重置链接无效或已失效')
            elif not user or not user['is_active']:
                raise HTTPException(400,'账号不可用')
            else:
                encoded=identity.hash_password(body.password)
                c.execute('UPDATE users SET password_hash=%s,updated=%s WHERE id=%s',
                          (encoded,now,item['user_id']))
                c.execute('UPDATE password_reset_tokens SET consumed_at=%s WHERE id=%s',(now,item['id']))
                c.execute('''UPDATE password_reset_tokens SET revoked_at=%s
                    WHERE user_id=%s AND id<>%s AND consumed_at IS NULL AND revoked_at IS NULL''',
                    (now,item['user_id'],item['id']))
                c.execute('UPDATE sessions SET revoked_at=%s WHERE user_id=%s AND revoked_at IS NULL',(now,item['user_id']))
                identity.audit(c,'user.password_reset','user',item['user_id'],actor_user_id=item['user_id'])
                identity.clear_rate_limit(c,[keys[1]])
                identity.issue_session(c,response,request,item['user_id'])
    if failure:
        raise failure
    return {'ok':True}


def _masked_phone(phone:str)->str:
    return phone[:3]+'****'+phone[-4:] if len(phone)>=8 else '***'


class InvitationCreate(StrictBody):
    expires_hours:int=Field(default=48,ge=1,le=720)
    note:str=Field(default='',max_length=200)


@app.get('/api/admin/invitations')
def list_invitations():
    with s.db() as c:
        return [dict(row) for row in c.execute('''SELECT id,created,expires,revoked_at,consumed_at,
            consumed_by,note FROM invitations ORDER BY created DESC LIMIT 200''')]


@app.post('/api/admin/invitations')
def create_invitation(body:InvitationCreate):
    principal=identity.current();raw=secrets.token_urlsafe(36);now=time.time();invite_id=s.uid('invite-')
    with s.db() as c:
        c.execute('''INSERT INTO invitations(id,token_hash,created_by,created,expires,note)
            VALUES(%s,%s,%s,%s,%s,%s)''',(invite_id,identity.digest(raw),principal.user_id,now,now+body.expires_hours*3600,body.note))
        identity.audit(c,'invitation.create','invitation',invite_id,payload={'expires':now+body.expires_hours*3600})
    # The raw token is returned exactly once and is never stored or logged.
    return {'id':invite_id,'token':raw,'expires':now+body.expires_hours*3600}


@app.delete('/api/admin/invitations/{invitation_id}')
def revoke_invitation(invitation_id:str):
    with s.db() as c:
        row=c.execute('''UPDATE invitations SET revoked_at=%s WHERE id=%s AND consumed_at IS NULL
            AND revoked_at IS NULL RETURNING id''',(time.time(),invitation_id)).fetchone()
        if not row:raise HTTPException(404,'邀请不存在或已失效')
        identity.audit(c,'invitation.revoke','invitation',invitation_id)
    return {'ok':True}


@app.get('/api/admin/users')
def admin_users():
    with s.db() as c:
        return [dict(row) for row in c.execute('''SELECT id,phone,nickname,platform_role,is_active,
            phone_verified_at,created,updated FROM users ORDER BY created,id''')]


class UserStateUpdate(StrictBody):
    is_active:bool


@app.patch('/api/admin/users/{user_id}')
def update_user_state(user_id:str,body:UserStateUpdate):
    principal=identity.current();now=time.time()
    with s.db() as c:
        identity.lock_identity_invariants(c)
        user=c.execute('SELECT * FROM users WHERE id=%s FOR UPDATE',(user_id,)).fetchone()
        if not user:raise HTTPException(404,'用户不存在')
        if user['platform_role']=='platform_admin' and not body.is_active:
            active=c.execute("SELECT COUNT(*) count FROM users WHERE platform_role='platform_admin' AND is_active").fetchone()['count']
            if active<=1:raise HTTPException(409,'不能停用最后一位有效平台管理员')
        if not body.is_active:
            sole_owner=c.execute('''SELECT wm.workspace_id FROM workspace_members wm
                WHERE wm.user_id=%s AND wm.role='owner' AND NOT EXISTS(
                    SELECT 1 FROM workspace_members other
                    JOIN users ou ON ou.id=other.user_id AND ou.is_active
                    WHERE other.workspace_id=wm.workspace_id AND other.role='owner' AND other.user_id<>wm.user_id
                ) LIMIT 1''',(user_id,)).fetchone()
            if sole_owner:raise HTTPException(409,'不能停用团队最后一位有效 owner')
        c.execute('UPDATE users SET is_active=%s,updated=%s WHERE id=%s',(body.is_active,now,user_id))
        if not body.is_active:
            c.execute('UPDATE sessions SET revoked_at=%s WHERE user_id=%s AND revoked_at IS NULL',(now,user_id))
            collaboration.revoke_assignments(c,user_id)
        identity.audit(c,'user.activate' if body.is_active else 'user.deactivate','user',user_id,
                       payload={'changed_by':principal.user_id})
    return {'id':user_id,'is_active':body.is_active}


class PasswordResetCreate(StrictBody):
    user_id:str=Field(min_length=1,max_length=100)
    expires_minutes:int=Field(default=30,ge=5,le=1440)


@app.post('/api/admin/password-resets')
def issue_password_reset(body:PasswordResetCreate):
    principal=identity.current();raw=secrets.token_urlsafe(36);reset_id=s.uid('reset-')
    with s.db() as c:
        user=identity.lock_password_recovery_user(c,body.user_id)
        now=time.time()
        if not user or not user['is_active']:
            raise HTTPException(404,'用户不存在')
        c.execute('UPDATE password_reset_tokens SET revoked_at=%s WHERE user_id=%s AND consumed_at IS NULL AND revoked_at IS NULL',(now,body.user_id))
        c.execute('''INSERT INTO password_reset_tokens(id,token_hash,user_id,created_by,created,expires)
            VALUES(%s,%s,%s,%s,%s,%s)''',(reset_id,identity.digest(raw),body.user_id,principal.user_id,now,now+body.expires_minutes*60))
        identity.audit(c,'password_reset.issue','user',body.user_id,payload={'reset_id':reset_id})
    return {'id':reset_id,'token':raw,'expires':now+body.expires_minutes*60}


class WorkspaceCreate(StrictBody):
    name:str=Field(min_length=1,max_length=100)
    owner_user_id:str=Field(min_length=1,max_length=100)


@app.get('/api/workspaces')
def workspaces():
    principal=identity.current()
    with s.db() as c:
        return [dict(row) for row in c.execute('''SELECT w.id,w.name,wm.role,w.created,w.updated
            FROM workspaces w JOIN workspace_members wm ON wm.workspace_id=w.id
            WHERE wm.user_id=%s ORDER BY w.name,w.id''',(principal.user_id,))]


@app.get('/api/admin/workspaces')
def admin_workspaces():
    with s.db() as c:
        return [dict(row) for row in c.execute('''SELECT w.id,w.name,w.created,w.updated,
            u.id owner_user_id,u.nickname owner_nickname
            FROM workspaces w
            JOIN workspace_members wm ON wm.workspace_id=w.id AND wm.role='owner'
            JOIN users u ON u.id=wm.user_id
            ORDER BY w.name,w.id,u.id''')]


@app.post('/api/admin/workspaces')
def create_workspace(body:WorkspaceCreate):
    principal=identity.current();wid=s.uid('workspace-');now=time.time();name=body.name.strip()
    with s.db() as c:
        identity.lock_identity_invariants(c)
        if not c.execute('SELECT 1 FROM users WHERE id=%s AND is_active',(body.owner_user_id,)).fetchone():
            raise HTTPException(404,'Owner 用户不存在')
        c.execute('INSERT INTO workspaces(id,name,created_by,created,updated) VALUES(%s,%s,%s,%s,%s)',
                  (wid,name,principal.user_id,now,now))
        c.execute("INSERT INTO workspace_members(workspace_id,user_id,role,created) VALUES(%s,%s,'owner',%s)",
                  (wid,body.owner_user_id,now))
        identity.audit(c,'workspace.create','workspace',wid,workspace_id=wid,
                       payload={'owner_user_id':body.owner_user_id})
    return {'id':wid,'name':name,'owner_user_id':body.owner_user_id}


@app.get('/api/workspaces/{workspace_id}/members')
def workspace_members(workspace_id:str):
    principal=identity.current()
    with s.db() as c:
        role=identity.workspace_role(c,principal,workspace_id)
        if not role:raise HTTPException(404,'团队不存在')
        rows=c.execute('''SELECT u.id,u.nickname,u.phone,wm.role,u.is_active
            FROM workspace_members wm JOIN users u ON u.id=wm.user_id
            WHERE wm.workspace_id=%s ORDER BY wm.role DESC,u.nickname,u.id''',(workspace_id,)).fetchall()
    return [{**dict(row),'phone':row['phone'] if role=='owner' else _masked_phone(row['phone'])} for row in rows]


class WorkspaceMemberUpdate(StrictBody):
    role:str=Field(pattern='^(owner|member)$')


@app.put('/api/workspaces/{workspace_id}/members/{user_id}')
def put_workspace_member(workspace_id:str,user_id:str,body:WorkspaceMemberUpdate):
    principal=identity.current();now=time.time()
    with s.db() as c:
        identity.lock_identity_invariants(c)
        identity.require_workspace_owner(c,principal,workspace_id)
        if not c.execute('SELECT 1 FROM users WHERE id=%s AND is_active',(user_id,)).fetchone():
            raise HTTPException(404,'用户不存在')
        existing=c.execute('''SELECT role FROM workspace_members
            WHERE workspace_id=%s AND user_id=%s FOR UPDATE''',(workspace_id,user_id)).fetchone()
        if existing and existing['role']=='owner' and body.role!='owner':
            other_owner=c.execute('''SELECT 1 FROM workspace_members wm JOIN users u ON u.id=wm.user_id
                WHERE wm.workspace_id=%s AND wm.role='owner' AND wm.user_id<>%s AND u.is_active LIMIT 1''',
                (workspace_id,user_id)).fetchone()
            if not other_owner:raise HTTPException(409,'不能降级最后一位有效团队 owner')
        if not existing:
            # Defensive cleanup for pre-P3/manual orphan rows. Rejoining a
            # Workspace must not silently revive historical Production roles.
            c.execute('''DELETE FROM production_members WHERE user_id=%s AND production_id IN(
                SELECT id FROM productions WHERE workspace_id=%s
            )''',(user_id,workspace_id))
        c.execute('''INSERT INTO workspace_members(workspace_id,user_id,role,created) VALUES(%s,%s,%s,%s)
            ON CONFLICT(workspace_id,user_id) DO UPDATE SET role=excluded.role''',(workspace_id,user_id,body.role,now))
        identity.audit(c,'workspace_member.put','user',user_id,workspace_id=workspace_id,payload={'role':body.role})
        if existing and existing['role']=='owner' and body.role!='owner':
            collaboration.revoke_assignments(c,user_id,workspace_id=workspace_id,lost_access_only=True)
    return {'workspace_id':workspace_id,'user_id':user_id,'role':body.role}


@app.delete('/api/workspaces/{workspace_id}/members/{user_id}')
def delete_workspace_member(workspace_id:str,user_id:str):
    principal=identity.current();now=time.time()
    with s.db() as c:
        identity.lock_identity_invariants(c)
        identity.require_workspace_owner(c,principal,workspace_id)
        member=c.execute('SELECT role FROM workspace_members WHERE workspace_id=%s AND user_id=%s FOR UPDATE',(workspace_id,user_id)).fetchone()
        if not member:raise HTTPException(404,'成员不存在')
        if member['role']=='owner':
            other_owner=c.execute('''SELECT 1 FROM workspace_members wm JOIN users u ON u.id=wm.user_id
                WHERE wm.workspace_id=%s AND wm.role='owner' AND wm.user_id<>%s AND u.is_active LIMIT 1''',
                (workspace_id,user_id)).fetchone()
            if not other_owner:raise HTTPException(409,'不能移除最后一位有效团队 owner')
        c.execute('DELETE FROM production_members WHERE user_id=%s AND production_id IN (SELECT id FROM productions WHERE workspace_id=%s)',(user_id,workspace_id))
        c.execute('DELETE FROM workspace_members WHERE workspace_id=%s AND user_id=%s',(workspace_id,user_id))
        collaboration.revoke_assignments(c,user_id,workspace_id=workspace_id)
        identity.audit(c,'workspace_member.remove','user',user_id,workspace_id=workspace_id)
    return {'ok':True,'revoked_at':now}


@app.get('/api/productions/{production_id}/members')
def production_members(production_id:str):
    principal=identity.current()
    with s.db() as c:
        identity.require_production(c,principal,production_id,'viewer')
        return [dict(row) for row in c.execute('''SELECT u.id,u.nickname,pm.role,u.is_active
            FROM production_members pm
            JOIN productions p ON p.id=pm.production_id
            JOIN workspace_members wm ON wm.workspace_id=p.workspace_id AND wm.user_id=pm.user_id
            JOIN users u ON u.id=pm.user_id
            WHERE pm.production_id=%s ORDER BY pm.role,u.nickname,u.id''',(production_id,))]


class ProductionMemberUpdate(StrictBody):
    role:str=Field(pattern='^(manager|editor|viewer)$')


@app.put('/api/productions/{production_id}/members/{user_id}')
def put_production_member(production_id:str,user_id:str,body:ProductionMemberUpdate):
    principal=identity.current();now=time.time()
    with s.db() as c:
        identity.lock_identity_invariants(c)
        identity.require_production(c,principal,production_id,'manager')
        production_row=c.execute('SELECT workspace_id FROM productions WHERE id=%s',(production_id,)).fetchone()
        from . import business_roles
        if business_roles.workflow(c,production_id):
            raise HTTPException(409,'此作品已启用五角色，请在作品分工页管理业务角色')
        if not production_row or not c.execute('SELECT 1 FROM workspace_members WHERE workspace_id=%s AND user_id=%s',(production_row['workspace_id'],user_id)).fetchone():
            raise HTTPException(409,'目标用户必须先加入作品所属团队')
        c.execute('''INSERT INTO production_members(production_id,user_id,role,created) VALUES(%s,%s,%s,%s)
            ON CONFLICT(production_id,user_id) DO UPDATE SET role=excluded.role''',(production_id,user_id,body.role,now))
        identity.audit(c,'production_member.put','user',user_id,workspace_id=production_row['workspace_id'],
                       production_id=production_id,payload={'role':body.role})
        if body.role=='viewer':
            collaboration.revoke_assignments(c,user_id,production_id=production_id,lost_access_only=True)
    return {'production_id':production_id,'user_id':user_id,'role':body.role}


@app.delete('/api/productions/{production_id}/members/{user_id}')
def delete_production_member(production_id:str,user_id:str):
    principal=identity.current()
    with s.db() as c:
        identity.lock_identity_invariants(c)
        identity.require_production(c,principal,production_id,'manager')
        p=c.execute('SELECT workspace_id FROM productions WHERE id=%s',(production_id,)).fetchone()
        c.execute('DELETE FROM production_members WHERE production_id=%s AND user_id=%s',(production_id,user_id))
        collaboration.revoke_assignments(c,user_id,production_id=production_id)
        identity.audit(c,'production_member.remove','user',user_id,workspace_id=p['workspace_id'],production_id=production_id)
    return {'ok':True}


@app.get('/api/admin/audit-events')
def audit_events(limit:int=100):
    with s.db() as c:
        return [dict(row) for row in c.execute('SELECT * FROM audit_events ORDER BY id DESC LIMIT %s',(min(max(limit,1),500),))]

def project(pid):
    with s.db() as c:
        row = c.execute("SELECT * FROM projects WHERE id=%s AND NOT EXISTS(SELECT 1 FROM deleted_items WHERE kind='project' AND item_id=projects.id)",(pid,)).fetchone()
        state=read_project_state(c,pid) if row else None
    if not row:
        raise HTTPException(404,'项目不存在')
    value=s.unpack(row)
    value['document']=state['document']
    value['production_revision']=state['production']['revision']
    value['objects']=[collaboration.public(row) for row in state.get('objects',[])]
    from .generation_staleness import reconcile_generation_staleness
    value['document']=reconcile_generation_staleness(
        state['episode_document'],platform_models.compiler_catalog(),
        production_context=state['production_context'],
    )
    from .adaptation import project_script_to_document
    with s.db() as c:
        value['document']=project_script_to_document(c,pid,value['document'],snapshot=state['script'])
        if row['object_collaboration']:
            graph=next((collaboration.public(item)['content'] for item in state.get('objects',[]) if item['kind']=='graph'),{})
            for node in value['document'].get('nodes',[]):
                if node['id'] in graph.get('positions',{}):
                    node['position']=graph['positions'][node['id']]
        principal=identity.current(False)
        if principal and value.get('production_id'):
            workspace_role,production_role=identity.production_role(c,principal,value['production_id'])
            level=(3 if workspace_role=='owner' else
                   identity._ROLE_LEVEL.get(production_role or '',0) if workspace_role is not None else 0)
            value['permissions']={
                'role':'owner' if workspace_role=='owner' else production_role,
                'can_read':level>=1,'can_generate':level>=2,'can_manage':level>=3,
                'legacy_document_write':False,
            }
            from . import business_roles
            value['permissions'].update(business_roles.permission_summary(c,value['production_id'],principal))
    return value

@app.get('/api/projects')
def projects(workspace_id:str|None=None):
    principal=identity.current()
    with s.db() as c:
        if workspace_id and not identity.workspace_role(c,principal,workspace_id):
            raise HTTPException(404,'团队不存在')
        return [dict(r) for r in c.execute('''SELECT e.id,e.name,e.revision,e.created,e.updated,e.production_id,e.episode_no,e.episode_title
            FROM projects e JOIN productions p ON p.id=e.production_id
            LEFT JOIN workspace_members wm ON wm.workspace_id=p.workspace_id AND wm.user_id=%s
            LEFT JOIN production_members pm ON pm.production_id=p.id AND pm.user_id=%s
            WHERE wm.user_id IS NOT NULL AND (wm.role='owner' OR pm.user_id IS NOT NULL)
            AND (%s::text IS NULL OR p.workspace_id=%s)
            AND NOT EXISTS(SELECT 1 FROM deleted_items WHERE kind='project' AND item_id=e.id)
            ORDER BY e.updated DESC''',(principal.user_id,principal.user_id,workspace_id,workspace_id))]

def production(production_id):
    with s.db() as c:
        row=c.execute('''SELECT p.*,
            (SELECT COUNT(*) FROM projects e WHERE e.production_id=p.id AND NOT EXISTS(
                SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=e.id
            )) episode_count
            FROM productions p WHERE p.id=%s''',(production_id,)).fetchone()
    if not row:raise HTTPException(404,'Production 不存在')
    value=dict(row)
    value['context']=normalize_production_context(json.loads(value.pop('shared_context')))
    principal=identity.current(False)
    if principal:
        with s.db() as c:
            workspace_role,production_role=identity.production_role(c,principal,production_id)
        level=(3 if workspace_role=='owner' else
               identity._ROLE_LEVEL.get(production_role or '',0) if workspace_role is not None else 0)
        value['permissions']={'role':'owner' if workspace_role=='owner' else production_role,
                              'can_read':level>=1,'can_generate':level>=2,'can_manage':level>=3,
                              'legacy_document_write':level>=3}
        from . import business_roles
        with s.db() as c:value['permissions'].update(business_roles.permission_summary(c,production_id,principal))
    return value

@app.get('/api/productions')
def productions(workspace_id:str|None=None):
    principal=identity.current()
    with s.db() as c:
        if workspace_id and not identity.workspace_role(c,principal,workspace_id):
            raise HTTPException(404,'团队不存在')
        return [dict(row) for row in c.execute('''SELECT p.id,p.name,p.revision,p.created,p.updated,
            p.workspace_id,CASE WHEN wm.role='owner' THEN 'owner' ELSE pm.role END role,
            (SELECT COUNT(*) FROM projects e WHERE e.production_id=p.id AND NOT EXISTS(
                SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=e.id
            )) episode_count
            FROM productions p
            LEFT JOIN workspace_members wm ON wm.workspace_id=p.workspace_id AND wm.user_id=%s
            LEFT JOIN production_members pm ON pm.production_id=p.id AND pm.user_id=%s
            WHERE (NOT EXISTS(
                SELECT 1 FROM projects e WHERE e.production_id=p.id
            ) OR EXISTS(
                SELECT 1 FROM projects e WHERE e.production_id=p.id AND NOT EXISTS(
                    SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=e.id
                )
            ))
            AND wm.user_id IS NOT NULL AND (wm.role='owner' OR pm.user_id IS NOT NULL)
            AND (%s::text IS NULL OR p.workspace_id=%s)
            ORDER BY p.updated DESC''',(principal.user_id,principal.user_id,workspace_id,workspace_id))]

class ProductionCreate(StrictBody):
    name:str=Field(default='未命名剧集',max_length=100)
    workspace_id:str|None=None


def _owned_workspace_id(connection, requested:str|None=None)->str:
    principal=identity.current()
    if requested:
        identity.require_workspace_owner(connection,principal,requested)
        return requested
    rows=connection.execute("SELECT workspace_id FROM workspace_members WHERE user_id=%s AND role='owner' ORDER BY workspace_id",
                            (principal.user_id,)).fetchall()
    if len(rows)!=1:
        raise HTTPException(400,'请明确选择要创建作品的团队')
    return rows[0]['workspace_id']

class ProductionUpdate(StrictBody):
    revision:int=Field(ge=1)
    name:str=Field(max_length=100)

@app.post('/api/productions')
def create_production(body:ProductionCreate):
    production_id=s.uid('production-')
    now=time.time();name=normalized_project_name(body.name)
    models=platform_models.compiler_catalog()
    context=new_production_context(default_platform_policy(models),default_model_pool(models))
    with s.db() as c:
        workspace_id=_owned_workspace_id(c,body.workspace_id)
        c.execute('INSERT INTO productions(id,name,revision,shared_context,created,updated,workspace_id) VALUES(%s,%s,1,%s,%s,%s,%s)',(production_id,name,s.dumps(context),now,now,workspace_id))
        identity.audit(c,'production.create','production',production_id,workspace_id=workspace_id,production_id=production_id)
    return production(production_id)

@app.patch('/api/productions/{production_id}')
def update_production(production_id:str,body:ProductionUpdate):
    name=body.name.strip()
    if not name:raise ValueError('作品名称不能为空')
    now=time.time()
    with s.db() as c:
        row=c.execute('SELECT revision FROM productions WHERE id=%s FOR UPDATE',(production_id,)).fetchone()
        if not row:raise HTTPException(404,'Production 不存在')
        if row['revision']!=body.revision:
            raise HTTPException(409,'Production 已在其他页面更新，请重新加载后编辑。')
        c.execute('UPDATE productions SET name=%s,revision=revision+1,updated=%s WHERE id=%s',(
            name,now,production_id,
        ))
    return {'id':production_id,'name':name,'revision':body.revision+1,'updated':now}

@app.get('/api/productions/{production_id}')
def read_production(production_id:str):
    return production(production_id)

@app.get('/api/productions/{production_id}/episodes')
def production_episodes(production_id:str):
    production(production_id)
    with s.db() as c:
        return [dict(row) for row in c.execute('''SELECT id,name,revision,created,updated,production_id,episode_no,episode_title
            FROM projects WHERE production_id=%s AND NOT EXISTS(
                SELECT 1 FROM deleted_items WHERE kind='project' AND item_id=projects.id
            ) ORDER BY episode_no,id''',(production_id,))]

@app.get('/api/productions/{production_id}/visual-usage')
def production_visual_usage(production_id:str):
    """Derive VisualVersion usage from canonical Episode shot bindings."""
    production(production_id)
    usage={}
    with s.db() as c:
        episodes=c.execute('''SELECT id,episode_no,episode_title,document,object_collaboration FROM projects
            WHERE production_id=%s AND NOT EXISTS(
                SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=projects.id
            ) ORDER BY episode_no,id''',(production_id,)).fetchall()
        from .collaboration_document import object_content
        shots_by_episode={}
        for row in c.execute('''SELECT project_id,content FROM collaboration_objects
            WHERE production_id=%s AND kind='shot' AND NOT deleted ORDER BY object_key,id''',(production_id,)):
            shots_by_episode.setdefault(row['project_id'],[]).append(object_content(row)['shot'])
    for episode in episodes:
        shots=(shots_by_episode.get(episode['id'],[]) if episode['object_collaboration']
               else json.loads(episode['document']).get('shots') or [])
        for shot in shots:
            bindings=shot.get('assetBindings') or {}
            values=[*(bindings.get('characters') or []),*(bindings.get('props') or [])]
            if isinstance(bindings.get('scene'),dict):values.append(bindings['scene'])
            for binding in values:
                version_id=binding.get('versionId') if isinstance(binding,dict) else None
                if not version_id:continue
                item=usage.setdefault(version_id,{'version_id':version_id,'episodes':{},'shots':[]})
                item['episodes'][episode['id']]={
                    'project_id':episode['id'],'episode_no':episode['episode_no'],
                    'episode_title':episode['episode_title'],
                }
                item['shots'].append({
                    'project_id':episode['id'],'episode_no':episode['episode_no'],
                    'shot_uid':str(shot.get('uid') or shot.get('id') or ''),
                    'shot_id':str(shot.get('id') or shot.get('uid') or ''),
                })
    return [{**item,'episodes':list(item['episodes'].values())} for item in usage.values()]

class EpisodeCreate(StrictBody):
    title:str=Field(default='',max_length=100)
    creation_mode:str|None=None

@app.post('/api/productions/{production_id}/episodes')
def create_episode(production_id:str,body:EpisodeCreate):
    document=new_document(default_platform_policy(platform_models.compiler_catalog()))
    now=time.time();pid=s.uid('project-')
    with s.db() as c:
        parent=c.execute('SELECT * FROM productions WHERE id=%s FOR UPDATE',(production_id,)).fetchone()
        if not parent:raise HTTPException(404,'Production 不存在')
        episode_no=c.execute(
            'SELECT COALESCE(MAX(episode_no),0)+1 value FROM projects WHERE production_id=%s',
            (production_id,),
        ).fetchone()['value']
        previous=c.execute('''SELECT document FROM projects WHERE production_id=%s
            AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=projects.id)
            ORDER BY episode_no DESC LIMIT 1''',(production_id,)).fetchone()
        previous_doc=json.loads(previous['document']) if previous else {}
        for key in ('ratio','duration','videoResolution','videoRatio','videoDuration','videoFormat','videoReferenceMode','dialogueMode'):
            if key in previous_doc:document[key]=previous_doc[key]
        mode=body.creation_mode if body.creation_mode is not None else previous_doc.get('creationMode','adaptation')
        if mode not in ('direct','adaptation'):raise ValueError('创作起点无效')
        document['creationMode']=mode
        title=body.title.strip() or f'第 {episode_no:02d} 集'
        c.execute('''INSERT INTO projects(
            id,name,revision,document,created,updated,production_id,episode_no,episode_title
        ) VALUES(%s,%s,1,%s,%s,%s,%s,%s,%s)''',(
            pid,title,s.dumps(episode_document_from_document(document)),now,now,production_id,episode_no,title,
        ))
        c.execute('UPDATE productions SET updated=%s WHERE id=%s',(now,production_id))
        from .adaptation import seed_episode_scripts
        seed_episode_scripts(c,pid)
        collaboration.initialize_episode(c,pid)
    return project(pid)

class ProjectCreate(StrictBody):
    five_role_workflow:bool=False
    creation_mode:str='adaptation'
    name:str=Field(default='未命名短片',max_length=100)
    workspace_id:str|None=None
    episode_title:str|None=Field(default=None,max_length=100)
    style:str|None=Field(default=None,max_length=200)
    ratio:str|None=None
    duration:float|None=Field(default=None,ge=5,le=3000)
    video_resolution:str=Field(default='720p')
    video_ratio:str=Field(default='16:9')
    video_duration:int=Field(default=-1)
    video_format:str=Field(default='mp4')
    video_reference_mode:str=Field(default='legacy')
    dialogue_mode:str=Field(default='full_dialogue')
    episode_count:int=Field(default=1,ge=1,le=500)
    platform:str=Field(default='通用短视频',min_length=1,max_length=100)
    brief:str|None=Field(default=None,max_length=24000)
    generation_policy:dict|None=None
    model_pool:dict|None=None
    film_bible:dict|None=None

def normalized_project_name(name:str)->str:
    return name.strip() or '未命名短片'

def project_create_document(body:ProjectCreate):
    providers=platform_models.compiler_catalog()
    document=new_document(default_platform_policy(providers))
    document['modelPool']=default_model_pool(providers)
    if body.creation_mode not in ('direct','adaptation'):raise ValueError('创作起点无效')
    document['creationMode']=body.creation_mode
    if body.style is not None:
        style=body.style.strip()
        if not style:raise ValueError('视觉风格不能为空')
        document['style']=style
    if body.ratio is not None:
        if body.ratio not in ('16:9','9:16','1:1'):
            raise ValueError('画幅只支持 16:9、9:16 或 1:1')
        document['ratio']=body.ratio
    if body.duration is not None:document['duration']=body.duration
    if body.video_resolution not in ('480p','720p','1080p'):
        raise ValueError('视频分辨率只支持 480p、720p 或 1080p')
    if body.video_ratio not in ('21:9','16:9','4:3','1:1','3:4','9:16','adaptive'):
        raise ValueError('视频宽高比无效')
    if body.video_duration!=-1 and not 4<=body.video_duration<=30:
        raise ValueError('视频输出时长只支持 4–30 秒或 -1')
    if body.video_format not in ('mp4','mov'):
        raise ValueError('视频格式只支持 mp4 或 mov')
    document['videoResolution']=body.video_resolution
    document['videoRatio']=body.video_ratio
    document['videoDuration']=body.video_duration
    document['videoFormat']=body.video_format
    if body.video_reference_mode not in ('legacy','multimodal','first_frame','first_last_frame'):
        raise ValueError('视频参考模式无效')
    if body.video_reference_mode!='legacy': document['videoReferenceMode']=body.video_reference_mode
    if body.dialogue_mode not in ('voice_sample','full_dialogue'):raise ValueError('对白生成方式无效')
    if body.dialogue_mode!='full_dialogue':document['dialogueMode']=body.dialogue_mode
    if body.brief is not None:document['brief']=body.brief
    if body.generation_policy is not None:
        document['generationPolicy']=validate_generation_policy(
            body.generation_policy,providers,allow_missing=False,
        )
    if body.model_pool is not None:
        document['modelPool']=validate_model_pool(body.model_pool,providers,allow_missing=False)
    validate_policy_in_pool(document['generationPolicy'],document['modelPool'])
    if body.film_bible is not None:
        if not isinstance(body.film_bible,dict):raise ValueError('Project Bible 必须是对象')
        unknown=set(body.film_bible)-{'story','style','continuity'}
        if unknown:raise ValueError('Project Bible 创建参数只支持 story、style、continuity')
        film_bible=empty_film_bible()
        for key in ('story','style','continuity'):
            value=body.film_bible.get(key,{})
            if not isinstance(value,dict):raise ValueError(f'Project Bible {key} 必须是对象')
            film_bible[key].update(value)
        document['filmBible']=film_bible
    return document

@app.post('/api/projects')
def create_project(body:ProjectCreate):
    pid = s.uid('project-');production_id=s.uid('production-')
    # Validate and compose the complete setup before opening the transaction so
    # invalid provider/model selections cannot leave partial Production rows.
    document = project_create_document(body)
    context=production_context_from_document(document)
    from .adaptation import configure_adaptation_format
    context.update(configure_adaptation_format(
        context,body.episode_count,document['duration'],document['ratio'],body.platform.strip(),
    ))
    now=time.time();name=normalized_project_name(body.name)
    episode_title=(body.episode_title or '').strip() if body.episode_title is not None else name
    episode_title=episode_title or '第 01 集'
    with s.db() as c:
        workspace_id=_owned_workspace_id(c,body.workspace_id)
        c.execute('INSERT INTO productions(id,name,revision,shared_context,created,updated,workspace_id) VALUES(%s,%s,1,%s,%s,%s,%s)',(production_id,name,s.dumps(context),now,now,workspace_id))
        if body.five_role_workflow:
            from . import business_roles
            business_roles.enable(c,production_id)
        c.execute('''INSERT INTO projects(
            id,name,revision,document,created,updated,production_id,episode_no,episode_title
        ) VALUES(%s,%s,1,%s,%s,%s,%s,1,%s)''',(pid,episode_title,s.dumps(episode_document_from_document(document)),now,now,production_id,episode_title))
        from .adaptation import seed_episode_scripts
        seed_episode_scripts(c,pid)
        collaboration.initialize_episode(c,pid)
        identity.audit(c,'production.create_legacy','production',production_id,workspace_id=workspace_id,production_id=production_id)
    return project(pid)

@app.get('/api/projects/{pid}')
def read_project(pid:str):
    return project(pid)

@app.delete('/api/projects/{pid}')
def delete_project(pid:str):
    from . import collaboration_lifecycle as lifecycle
    with s.db() as c:
        lifecycle.authorize(c,'project',pid)
        row=c.execute('''SELECT e.*,p.workspace_id FROM projects e JOIN productions p ON p.id=e.production_id
            WHERE e.id=%s AND NOT EXISTS(SELECT 1 FROM deleted_items WHERE kind='project' AND item_id=e.id)''',(pid,)).fetchone()
        if not row: raise HTTPException(404,'项目不存在')
        active=c.execute("SELECT COUNT(*) count FROM jobs WHERE project_id=%s AND status IN ('queued','running')",(pid,)).fetchone()['count']
        if active: raise HTTPException(409,f'项目仍有 {active} 个运行中任务，请先取消后再移入回收站。')
        lifecycle.fence(c,'project',pid,'trash')
        c.execute("INSERT INTO deleted_items(kind,item_id,project_id,deleted_at) VALUES('project',%s,%s,%s)",(pid,pid,time.time()))
        identity.audit(c,'project.trash','project',pid,workspace_id=row['workspace_id'],production_id=row['production_id'])
    return {'deleted':pid,'soft':True}

@app.get('/api/projects/{pid}/storyboard-sheet')
def storyboard_sheet(pid:str,columns:int=3,page:int=1):
    from .contact_sheet import render_sheet
    return Response(render_sheet(project(pid),columns,page),media_type='image/png',headers={'Content-Disposition':f'attachment; filename="storyboard-{page}.png"'})

class ProjectSave(StrictBody):
    name:str=Field(max_length=100)
    revision:int
    production_revision:int|None=None
    document:dict

@app.put('/api/projects/{pid}')
def save_project(pid:str,body:ProjectSave):
    raise HTTPException(410, '整份项目保存已退役；请使用对象命令及元数据接口。旧快照未写入任何内容。')

@app.get('/api/projects/{pid}/revisions')
def revisions(pid:str):
    project(pid)
    with s.db() as c:
        return [dict(r) for r in c.execute('SELECT id,revision,created FROM revisions WHERE project_id=%s ORDER BY revision DESC LIMIT 100',(pid,))]

@app.get('/api/projects/{pid}/revisions/{rid}')
def revision(pid:str,rid:str):
    with s.db() as c:
        row=c.execute('SELECT * FROM revisions WHERE project_id=%s AND id=%s',(pid,rid)).fetchone()
    if not row: raise HTTPException(404,'历史版本不存在')
    value=s.unpack(row)
    value['document']=migrate_document(value['document'])
    return value

def asset_row(aid):
    with s.db() as c:
        row=c.execute("SELECT * FROM assets WHERE id=%s AND NOT EXISTS(SELECT 1 FROM deleted_items WHERE kind='asset' AND item_id=assets.id)",(aid,)).fetchone()
    if not row: raise HTTPException(404,'素材不存在')
    return s.unpack(row)

def asset_public(row):
    public={**{k:v for k,v in row.items() if k!='path'},'url':f'/api/assets/{row["id"]}/file'}
    public['status']='active'
    metadata=public.get('metadata') or {}
    job_input=metadata.get('input') if isinstance(metadata,dict) else {}
    if isinstance(job_input,dict):
        public['model_id']=job_input.get('model_id')
        public['generation_fingerprint']=metadata.get('generationFingerprint')
        visual=job_input.get('visual_reference') or {}
        if isinstance(visual,dict):public['visual_version_id']=visual.get('versionId')
    return public

ASSET_CATEGORIES={'character','scene','prop','shot','music','sfx','voice','reference','motion_reference','other'}
ASSET_KINDS={'image','video','audio','subtitle'}

def asset_category(value):
    if value not in ASSET_CATEGORIES:raise ValueError('素材分类无效')
    return value

@app.get('/api/projects/{pid}/assets')
def assets(pid:str,category:str|None=None,kind:str|None=None,scope:str='episode'):
    owner=project(pid)
    if category is not None:asset_category(category)
    if kind is not None and kind not in ASSET_KINDS:raise ValueError('媒体类型无效')
    if scope not in ('episode','production'):raise ValueError('素材范围无效')
    clauses=["NOT EXISTS(SELECT 1 FROM deleted_items WHERE kind='asset' AND item_id=assets.id)"]
    params=[]
    if scope=='production':clauses.append('assets.production_id=%s');params.append(owner['production_id'])
    else:clauses.append('assets.project_id=%s');params.append(pid)
    if category is not None:clauses.append('category=%s');params.append(category)
    if kind is not None:clauses.append('kind=%s');params.append(kind)
    with s.db() as c:
        rows=c.execute('''SELECT assets.*,origin.name origin_project_name,
            origin.episode_no origin_episode_no FROM assets
            JOIN projects origin ON origin.id=assets.project_id WHERE '''+
            ' AND '.join(clauses)+' ORDER BY assets.created DESC',params)
        return [asset_public(s.unpack(r)) for r in rows]

@app.get('/api/productions/{production_id}/assets')
def production_assets(production_id:str,category:str|None=None,kind:str|None=None):
    production(production_id)
    if category is not None:asset_category(category)
    if kind is not None and kind not in ASSET_KINDS:raise ValueError('媒体类型无效')
    clauses=['assets.production_id=%s',"NOT EXISTS(SELECT 1 FROM deleted_items WHERE kind='asset' AND item_id=assets.id)"]
    params=[production_id]
    if category is not None:clauses.append('category=%s');params.append(category)
    if kind is not None:clauses.append('kind=%s');params.append(kind)
    with s.db() as c:
        rows=c.execute('''SELECT assets.*,origin.name origin_project_name,
            origin.episode_no origin_episode_no FROM assets
            JOIN projects origin ON origin.id=assets.project_id WHERE '''+
            ' AND '.join(clauses)+' ORDER BY assets.created DESC',params)
        return [asset_public(s.unpack(row)) for row in rows]

@app.post('/api/projects/{pid}/assets')
async def upload(pid:str,file:UploadFile=File(...),category:str='other',voice_reference:bool=False):
    owner=project(pid)
    category=asset_category(category)
    name=Path(file.filename or 'asset').name
    ext=Path(name).suffix.lower()
    if voice_reference and ext not in ('.mp3','.wav'):raise ValueError('声音样本仅支持MP3/WAV')
    allowed={'.png':'image','.jpg':'image','.jpeg':'image','.webp':'image','.mp4':'video','.webm':'video','.mov':'video','.wav':'audio','.mp3':'audio','.m4a':'audio','.srt':'subtitle'}
    if ext not in allowed: raise HTTPException(400,'支持 PNG/JPG/WebP、MP4/WebM/MOV、WAV/MP3/M4A、SRT')
    aid=s.uid('asset-'); path=s.asset_path(aid,ext); total=0
    try:
        with path.open('wb') as out:
            while chunk:=await file.read(1024*1024):
                total+=len(chunk)
                if voice_reference and total>30*1024**2:raise HTTPException(413,'声音样本不能超过30 MB')
                if total>2*1024**3: raise HTTPException(413,'单个素材不能超过 2GB')
                out.write(chunk)
        metadata={'bytes':total}
        if allowed[ext]=='image':
            from PIL import Image
            with Image.open(path) as img:
                img.verify()
            with Image.open(path) as img:
                metadata.update(width=img.width,height=img.height)
        elif allowed[ext] in ('video','audio'):
            from .media import probe
            metadata.update(await asyncio.to_thread(probe,path))
        if voice_reference:
            from .voice_reference_uploads import validate_file
            metadata.update(await asyncio.to_thread(validate_file,path))
        with s.db() as c:
            # Upload/probe occurs outside the transaction. Recheck live access
            # before registering material after potentially long file I/O.
            collaboration.lock_identity(c)
            collaboration.project_scope(c,pid,'editor')
            c.execute('INSERT INTO assets(id,project_id,name,kind,path,mime,metadata,created,category,source,production_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(aid,pid,name,allowed[ext],path.name,mimetypes.guess_type(name)[0] or 'application/octet-stream',s.dumps(metadata),time.time(),category,'uploaded',owner['production_id']))
        return asset_public(asset_row(aid))
    except Exception:
        path.unlink(missing_ok=True)
        raise

class AssetUpdate(StrictBody):
    category:str

class VoiceReferenceAdmission(StrictBody):
    authorized:bool=Field(default=False,strict=True)

@app.post('/api/projects/{pid}/assets/{aid}/voice-reference')
def admit_voice_reference(pid:str,aid:str,body:VoiceReferenceAdmission):
    if not body.authorized:raise ValueError('请确认拥有该声音的使用权或已获授权')
    with s.db() as c:collaboration.project_scope(c,pid,'editor')
    asset=reference_asset(pid,aid)
    path=(s.ASSETS/asset['path']).resolve()
    if asset['kind']!='audio' or not path.is_relative_to(s.ASSETS.resolve()) or not path.is_file():
        raise ValueError('请选择当前作品可访问的音频素材')
    from .voice_reference_uploads import validate_file
    from .motion_references import file_hash
    from datetime import datetime,timezone
    metadata=validate_file(path);digest=file_hash(path)
    with s.db() as c:
        # Decode outside locks; recheck membership and soft deletion before admission.
        collaboration.lock_identity(c);scope=collaboration.project_scope(c,pid,'editor')
        row=c.execute('''SELECT * FROM assets WHERE id=%s AND production_id=%s
            AND NOT EXISTS(SELECT 1 FROM deleted_items WHERE kind='asset' AND item_id=assets.id) FOR UPDATE''',
            (aid,scope['production_id'])).fetchone()
        if not row or row['path']!=asset['path']:raise HTTPException(409,'声音素材已变化，请刷新后重试')
        previous=s.unpack(row).get('metadata') or {};receipt=previous.get('voice_reference')
        if receipt and receipt.get('sha256')!=digest:raise HTTPException(409,'已确认样本文件发生变化，请重新上传')
        receipt=receipt or {'authorized_at':datetime.now(timezone.utc).isoformat(),
            'declared_by':identity.current().user_id,'declaration':'user_declared','sha256':digest}
        c.execute('UPDATE assets SET metadata=%s WHERE id=%s',(s.dumps({**previous,**metadata,'voice_reference':receipt}),aid))
    return asset_public(asset_row(aid))

@app.patch('/api/projects/{pid}/assets/{aid}')
def update_asset(pid:str,aid:str,body:AssetUpdate):
    category=asset_category(body.category)
    with s.db() as c:
        collaboration.lock_identity(c)
        collaboration.project_scope(c,pid,'editor')
        reference_asset(pid,aid)
        c.execute('UPDATE assets SET category=%s WHERE id=%s',(category,aid))
    return asset_public(asset_row(aid))

@app.delete('/api/projects/{pid}/assets/{aid}')
def delete_asset(pid:str,aid:str):
    from . import collaboration_lifecycle as lifecycle
    with s.db() as c:
        lifecycle.authorize(c,'asset',aid)
        collaboration.project_scope(c,pid,'manager')
        row=reference_asset(pid,aid)
        lifecycle.protect_referenced_asset(c,row['production_id'],aid)
        c.execute("INSERT INTO deleted_items(kind,item_id,project_id,deleted_at) VALUES('asset',%s,%s,%s)",(aid,row['project_id'],time.time()))
        workspace=c.execute('SELECT workspace_id FROM productions WHERE id=%s',(row['production_id'],)).fetchone()
        identity.audit(c,'asset.trash','asset',aid,workspace_id=workspace['workspace_id'],production_id=row['production_id'])
        episode_ids=[item['id'] for item in c.execute('SELECT id FROM projects WHERE production_id=%s',(row['production_id'],))]
        for episode_id in episode_ids:s.event(episode_id,{'type':'asset_deleted','id':aid},connection=c)
    return {'deleted':aid,'soft':True}

@app.get('/api/trash')
def trash():
    principal=identity.current()
    with s.db() as c:
        allowed=identity.visible_production_ids(c,principal)
        deleted_projects=[dict(row) for row in c.execute("SELECT p.id,p.name,d.deleted_at FROM deleted_items d JOIN projects p ON p.id=d.item_id WHERE d.kind='project' AND p.production_id=ANY(%s) ORDER BY d.deleted_at DESC",(allowed,))]
        deleted_assets=[dict(row) for row in c.execute("SELECT a.id,a.name,a.kind,a.category,a.project_id,a.production_id,p.name project_name,d.deleted_at FROM deleted_items d JOIN assets a ON a.id=d.item_id JOIN projects p ON p.id=a.project_id WHERE d.kind='asset' AND a.production_id=ANY(%s) ORDER BY d.deleted_at DESC",(allowed,))]
        deleted_sources=[dict(row) for row in c.execute('''SELECT sd.id,sd.title name,sd.type,
            sd.production_id,p.name production_name,
            (SELECT COUNT(*) FROM source_chapters sc WHERE sc.source_id=sd.id AND NOT EXISTS(
                SELECT 1 FROM deleted_items dc WHERE dc.kind='chapter' AND dc.item_id=sc.id
            )) chapter_count,
            d.deleted_at
            FROM deleted_items d JOIN source_documents sd ON sd.id=d.item_id
            JOIN productions p ON p.id=sd.production_id
            WHERE d.kind='source' AND sd.production_id=ANY(%s) ORDER BY d.deleted_at DESC''',(allowed,))]
        deleted_chapters=[dict(row) for row in c.execute('''SELECT sc.id,sc.title name,sc.chapter_no,
            sd.id source_id,sd.title source_name,sd.production_id,p.name production_name,d.deleted_at
            FROM deleted_items d JOIN source_chapters sc ON sc.id=d.item_id
            JOIN source_documents sd ON sd.id=sc.source_id JOIN productions p ON p.id=sd.production_id
            WHERE d.kind='chapter' AND sd.production_id=ANY(%s) ORDER BY d.deleted_at DESC''',(allowed,))]
    return {'projects':deleted_projects,'assets':deleted_assets,'sources':deleted_sources,'chapters':deleted_chapters}

@app.post('/api/trash/{kind}/{item_id}/restore')
def restore_deleted_item(kind:str,item_id:str):
    from . import collaboration_lifecycle as lifecycle
    if kind not in ('project','asset','source','chapter'):raise HTTPException(400,'回收站类型无效')
    with s.db() as c:
        lifecycle.authorize(c,kind,item_id)
        row=c.execute('SELECT * FROM deleted_items WHERE kind=%s AND item_id=%s FOR UPDATE',(kind,item_id)).fetchone()
        if not row:raise HTTPException(404,'回收站中没有该项目')
        if kind=='asset':
            hidden_project=c.execute("SELECT 1 FROM deleted_items WHERE kind='project' AND item_id=%s",(row['project_id'],)).fetchone()
            if hidden_project:raise HTTPException(409,'请先恢复素材所属项目。')
        c.execute('DELETE FROM deleted_items WHERE kind=%s AND item_id=%s',(kind,item_id))
        if kind=='asset':
            asset=c.execute('SELECT production_id FROM assets WHERE id=%s',(item_id,)).fetchone()
            episode_ids=[item['id'] for item in c.execute('SELECT id FROM projects WHERE production_id=%s',(asset['production_id'],))] if asset and asset['production_id'] else [row['project_id']]
        elif kind=='source':
            episode_ids=production_event_targets(c,row['project_id'])
        elif kind=='chapter':
            chapter=c.execute('''SELECT sd.id source_id FROM source_chapters sc
                JOIN source_documents sd ON sd.id=sc.source_id WHERE sc.id=%s''',(item_id,)).fetchone()
            hidden_source=c.execute("SELECT 1 FROM deleted_items WHERE kind='source' AND item_id=%s",(chapter['source_id'],)).fetchone() if chapter else None
            if hidden_source:raise HTTPException(409,'请先恢复章节所属原著。')
            episode_ids=production_event_targets(c,row['project_id'])
        else:episode_ids=[row['project_id']] if row['project_id'] else []
        lifecycle.fence(c,kind,item_id,'untrash')
        production_id=identity.production_for_resource(c,kind,item_id)
        workspace=c.execute('SELECT workspace_id FROM productions WHERE id=%s',(production_id,)).fetchone() if production_id else None
        identity.audit(c,'trash.restore',kind,item_id,
                       workspace_id=workspace['workspace_id'] if workspace else None,
                       production_id=production_id)
        for episode_id in episode_ids:s.event(episode_id,{'type':'restored','kind':kind,'id':item_id},connection=c)
    return {'restored':item_id,'kind':kind}

@app.get('/api/assets/{aid}/file')
def asset_file(aid:str):
    row=asset_row(aid)
    path=s.stored_asset_path(row['path'])
    if not path.is_relative_to(s.ASSETS) or not path.is_file(): raise HTTPException(404,'素材文件丢失')
    return FileResponse(path,media_type=row['mime'],filename=row['name'],content_disposition_type='inline')

@app.get('/api/provider-assets/{aid}')
def provider_asset_file(aid:str,expires:int,signature:str,purpose:str,request:Request):
    from .provider_assets import valid_signature
    if not valid_signature(aid,expires,signature,request.method,purpose):
        raise HTTPException(403,'素材访问链接无效或已过期')
    row=asset_row(aid)
    path=s.stored_asset_path(row['path'])
    if not path.is_relative_to(s.ASSETS) or not path.is_file():
        raise HTTPException(404,'素材文件丢失')
    return FileResponse(
        path,media_type=row['mime'],filename=row['name'],content_disposition_type='inline',
        headers={'Cache-Control':'private, no-store'},
    )

@app.get('/api/system')
def system():
    return {'execution_mode':'external-api','worker':'separate-process','models':[],'templates':TEMPLATES}

@app.get('/api/settings')
def settings():
    principal=identity.current()
    return {**platform_models.catalog(), 'read_only':not principal.is_admin,
            'ffmpeg':s.get_setting('ffmpeg','ffmpeg') if principal.is_admin else None}

@app.put('/api/settings')
async def update_settings(request:Request):
    if not identity.current().is_admin:
        raise HTTPException(403,'需要平台管理员权限')
    body=await request.json()
    if isinstance(body,dict) and 'providers' in body:
        raise HTTPException(410,'旧供应商配置入口已退役，请使用平台模型管理')
    if not isinstance(body,dict) or set(body)-{'ffmpeg'}:
        raise ValueError('设置字段无效')
    if 'ffmpeg' in body:
        if not isinstance(body['ffmpeg'],str) or not body['ffmpeg'].strip() or len(body['ffmpeg'])>2048:
            raise ValueError('FFmpeg 路径无效')
        with s.db() as c:
            c.execute("""INSERT INTO settings(key,value) VALUES('ffmpeg',%s)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value""",(s.dumps(body['ffmpeg']),))
            identity.audit(c,'platform_settings.update','settings','global',payload={'keys':['ffmpeg']})
    return settings()

def retired_provider_entry():
    if not identity.current().is_admin:
        raise HTTPException(403,'需要平台管理员权限')
    raise HTTPException(410,'旧供应商入口已退役，请使用平台模型管理；未发起上游调用')

@app.get('/api/providers/{provider_id}/models')
def provider_models(provider_id:str,kind:str|None=None):
    retired_provider_entry()

@app.post('/api/providers/{provider_id}/verify')
def verify_provider(provider_id:str):
    retired_provider_entry()

@app.post('/api/providers/{provider_id}/test')
def test_provider(provider_id:str,kind:str='text'):
    retired_provider_entry()

class JobCreate(StrictBody):
    node_id:str
    kind:str
    submission_id:str=Field(min_length=8,max_length=200)
    input:dict

class PromptTemplateSave(StrictBody):
    revision:int=Field(ge=0)
    name:str=Field(min_length=1,max_length=100)
    kind:str
    content:str=Field(min_length=1,max_length=24000)
    deleted:bool=False

def reference_asset(pid,aid):
    with s.db() as c:
        row=c.execute('''SELECT a.*,origin.id origin_project_id,
            origin.production_id origin_production_id,
            target.id target_project_id,target.production_id target_production_id
            FROM assets a
            JOIN projects origin ON origin.id=a.project_id
            JOIN projects target ON target.id=%s
            WHERE a.id=%s AND NOT EXISTS(
                SELECT 1 FROM deleted_items d WHERE d.kind='asset' AND d.item_id=a.id
            )''',(pid,aid)).fetchone()
    if not row:raise HTTPException(404,'素材不存在')
    asset_production_id=row['production_id'] or row['origin_production_id'] or row['origin_project_id']
    target_production_id=row['target_production_id'] or row['target_project_id']
    if asset_production_id!=target_production_id:
        raise ValueError('不能引用其他 Production 的素材')
    return s.unpack(row)

@app.get('/api/prompt-library')
def prompt_library():
    from .prompt_library import read
    return read()

@app.put('/api/prompt-library/{tid}')
def save_prompt_template(tid:str,body:PromptTemplateSave):
    raise HTTPException(410, '提示词写入已移至平台管理接口')


@app.put('/api/admin/prompt-templates/{tid}')
def save_platform_prompt_template(tid:str,body:PromptTemplateSave):
    from .prompt_library import save
    return save(tid,body)

class ImageSpecPreview(StrictBody):
    node_id: str
    model_id: str
    node_data: dict = Field(default_factory=dict)
    parameters: dict = Field(default_factory=dict)
    imageSettings: dict = Field(default_factory=dict)
    ratio: str | None = None
    videoResolution: str | None = None


@app.post('/api/projects/{pid}/image-spec')
def image_spec_preview(pid:str,body:ImageSpecPreview):
    with s.db() as c:
        collaboration.project_scope(c,pid,'viewer')
        state=read_project_state(c,pid)
        from .generation_policy import require_model_in_pool
        require_model_in_pool('image',body.model_id,state['production_context'].get('modelPool'))
        document=dict(state['document'])
        if body.ratio is not None: document['ratio']=body.ratio
        if body.videoResolution is not None:
            if body.videoResolution not in ('480p','720p','1080p'): raise ValueError('视频分辨率无效')
            document['videoResolution']=body.videoResolution
        # References/prompts are validated on submission, not by this local
        # parameter-only preview. It never queues or contacts a provider.
        binding=platform_models.resolve(c,body.model_id,'image',
            {**body.node_data,'parameters':body.parameters,'imageSettings':body.imageSettings},
            document=document,node_id=body.node_id,preview=True)
        return binding.image_spec


class VideoSpecPreview(StrictBody):
    node_id: str
    model_id: str
    node_data: dict = Field(default_factory=dict)
    shot: dict = Field(default_factory=dict)
    videoReferenceMode: str | None = None
    dialogueMode: str | None = None


@app.post('/api/projects/{pid}/video-spec')
def video_spec_preview(pid:str,body:VideoSpecPreview):
    import copy
    from .motion_references import compile_motion_input, _shot_for_video_node
    from .video_dialogue import compile_shot_video_input, bind_fixed_dialogue_audio
    model_validation.reject_private_overrides(body.model_dump())
    if set(body.shot)-{'motionReference','videoReferenceMode','video_prompt','duration','camera','dialogueMode'}:
        raise ValueError('视频预览只接受本镜头参考设置，不接受其他业务对象')
    with s.db() as c:
        collaboration.project_scope(c,pid,'viewer')
        state=read_project_state(c,pid)
    from .generation_policy import require_model_in_pool
    require_model_in_pool('video',body.model_id,state['production_context'].get('modelPool'))
    document=copy.deepcopy(state['document'])
    shot=_shot_for_video_node(document,body.node_id)
    node=next((item for item in document.get('nodes',[]) if item['id']==body.node_id),None)
    if shot is None or node is None or node.get('data',{}).get('kind')!='video':
        raise HTTPException(404,'视频预览目标镜头不存在')
    shot.update(body.shot)
    node['data'].update(body.node_data)
    if 'video_prompt' in body.shot: node['data']['prompt']=shot['video_prompt']
    if body.videoReferenceMode is not None: document['videoReferenceMode']=body.videoReferenceMode
    if body.dialogueMode is not None:document['dialogueMode']=body.dialogueMode
    provider=next((item for item in platform_models.compiler_catalog() if item['id']==body.model_id),None)
    if provider is None: raise ValueError('请选择已发布的平台视频模型')
    data={**node['data'],'model_id':body.model_id}
    # Collect saved graph inputs just as the single-node submit UI does.
    nodes={item['id']:item['data'] for item in document.get('nodes',[])}
    data['asset_ids']=list(dict.fromkeys([*data.get('asset_ids',[]), *[
        nodes[edge['source']]['assetId'] for edge in document.get('edges',[])
        if edge.get('target')==body.node_id and nodes.get(edge.get('source'),{}).get('kind')=='image'
        and nodes[edge['source']].get('assetId')]]))
    data=compile_shot_video_input(document,body.node_id,'video',data,parameter_rules=provider['rules'])
    if provider['type'] in ('volcengine_ark','runninghub') or (provider['type']=='hc_atom' and provider['capabilities'].get('audio_reference')):
        data=bind_fixed_dialogue_audio(document,body.node_id,'video',data,
            production_assets(state['project']['production_id'],kind='audio'),
            parameter_rules=provider['rules'],require_canonical=provider['type']=='hc_atom')
    data=compile_motion_input(document,body.node_id,'video',data,pid,provider)
    with s.db() as c:
        binding=platform_models.resolve(c,body.model_id,'video',data,document=document,node_id=body.node_id)
        selected=platform_models.config_for_binding(c,binding)
    if (data.get('motion_reference') or (data.get('voice_samples') and provider['type']=='hc_atom')) and provider['type'] in ('volcengine_ark','hc_atom'):
        from .provider_assets import public_asset_base
        public_asset_base(selected)
    data['parameters']=binding.parameters
    # Deliberate whitelist: no private model identity, provider URL, credentials, or arbitrary node fields.
    return {key:data[key] for key in ('prompt','generation_mode','motion_reference','reference_manifest',
        'motion_warnings','planned_shot_duration','shot_duration','parameters','dialogue_audio_mode','dialogue_mode','voice_samples') if key in data}


def create_job_record(c,pid,body,*,object_state=None,entrypoint='job'):
    from .job_contracts import freeze_prompt_contract
    from .job_candidates import freeze_relation
    model_validation.reject_private_overrides(body.input)
    body.input.pop('image_spec',None)  # Read-only projection, never trust caller metadata.
    body.input.pop('video_spec',None)
    body.input.pop('storyboard_visual_context',None)
    submitted_input=body.input
    film_bible_storyboard=body.kind=='storyboard' and body.input.get('film_bible')
    if not film_bible_storyboard:
        body.input=freeze_prompt_contract(body.kind,body.input)
    if body.kind not in ('text','storyboard','image','video','audio','export'): raise ValueError('不支持的任务类型')
    job_admission.lock(c)
    owner,actor=job_admission.scope(c,pid,entrypoint)
    target=freeze_relation(c,pid,body)
    if not target:
        from .object_job_candidates import freeze
        target=freeze(c,pid,body,object_state)
    if film_bible_storyboard:
        # object_job_candidates.freeze has now captured the canonical visual
        # objects under their revisions and production visual binding guard.
        body.input=freeze_prompt_contract(body.kind,body.input)
    old=c.execute('''SELECT * FROM jobs WHERE workspace_id=%s AND actor_user_id=%s
        AND submission_namespace=%s AND submission_id=%s''',
        (owner['workspace_id'],actor.user_id,entrypoint,body.submission_id)).fetchone()
    if old:
        if old['project_id']!=pid or old['node_id']!=body.node_id or old['kind']!=body.kind:
            raise HTTPException(409,'同一提交标识不能对应不同目标')
        state=object_state or read_project_state(c,pid)
        original=job_admission.replay_binding(c,old,body,state['document'] if state else {})
        if old['input_hash']!=job_admission.fingerprint(pid,body,target,original):
            raise HTTPException(409,'同一提交标识不能对应不同输入、对象版本或分配')
        return s.unpack(old)
    if (body.input.get('adaptation_generation') or {}).get('mode')=='episode':
        active=c.execute("SELECT id FROM jobs WHERE production_id=%s AND node_id=%s AND status IN ('queued','running') LIMIT 1",
            (owner['production_id'],body.node_id)).fetchone()
        if active:raise HTTPException(409,'本集规划已有任务排队或运行中')
    if body.input.get('source_event_extraction') is not None:
        active=c.execute("""SELECT id FROM jobs WHERE production_id=%s AND node_id=%s
            AND kind='text' AND status IN ('queued','running') LIMIT 1""",
            (owner['production_id'],body.node_id)).fetchone()
        if active:raise HTTPException(409,'所选章节已有事件提取任务排队或运行中，请等待完成或取消后再提交')
    if body.input.get('episode_script_generation') is not None:
        active=c.execute("SELECT id FROM jobs WHERE project_id=%s AND node_id=%s AND status IN ('queued','running') LIMIT 1",
                         (pid,body.node_id)).fetchone()
        if active:raise HTTPException(409,'本集已有剧本任务排队或运行中，请等待完成后再生成')
    if body.input.get('visual_reference') is not None:
        active=c.execute("""SELECT * FROM jobs
            WHERE project_id=%s AND node_id=%s AND kind=%s AND status IN ('queued','running')
            ORDER BY created DESC LIMIT 1""",(pid,body.node_id,body.kind)).fetchone()
        if active:
            raise HTTPException(409,'该资产参考图已有任务排队或运行中，请等待完成后再生成')
    if body.kind!='export' and not body.input.get('prompt','').strip(): raise ValueError('请输入生成描述')
    if body.kind=='video':
        from .state_review import require_video_source_reviews
        state=read_project_state(c,pid)
        if state: require_video_source_reviews(state['document'],body.node_id)
    if body.kind in ('text','storyboard') and body.input.get('target_duration') is not None:
        if not 1<=float(body.input['target_duration'])<=3000:raise ValueError('剧本或分镜目标时长应为 1–3000 秒')
    if body.input.get('visual_reference') is not None:
        from .visual_references import validate_visual_reference_job
        state=read_project_state(c,pid)
        validate_visual_reference_job(
            state['document'] if state else {},body.node_id,body.kind,
            body.input,platform_models.compiler_catalog(),
        )
    binding = selected = None
    if body.kind!='export':
        model_id=body.input.get('model_id')
        if not isinstance(model_id,str) or not model_id.strip():
            raise ValueError('请选择已发布的平台 model_id；不会自动回退其他模型')
        state=read_project_state(c,pid)
        from .generation_policy import require_model_in_pool
        require_model_in_pool(body.kind,model_id,
            (state or {}).get('production_context',{}).get('modelPool'))
        binding=platform_models.resolve(c,model_id,body.kind,submitted_input,
            document=state['document'] if state else {},node_id=body.node_id)
        selected=platform_models.config_for_binding(c,binding)
        if target.get('mode')=='voice':
            from .voice_identity import validate_parameters
            validate_parameters(c,target['target'],binding.parameters)
    if selected and selected['type']=='minimax':
        from .minimax_video import payload
        if body.kind!='video':raise ValueError('MiniMax 原生服务仅支持视频节点')
        payload({**body.input,**binding.parameters,'parameters':binding.parameters},selected)
    references=list(body.input.get('asset_ids',[]))
    multimodal=(body.input.get('generation_mode') or {}).get('requested')=='multimodal'
    if selected and (body.input.get('motion_reference') or (body.input.get('voice_samples') and selected['type']=='hc_atom')) and selected['type'] in ('volcengine_ark','hc_atom'):
        from .provider_assets import public_asset_url
        public_asset_url(selected, 'motion-preflight')
    if body.input.get('end_asset_id'):references.append(body.input['end_asset_id'])
    if selected and selected.get('type')=='volcengine_ark':
        from .providers.volcengine_ark import max_image_references, model_capabilities
        ark_video_reference_count=(
            len(body.input['image_reference_sources'])
            if 'image_reference_sources' in body.input
            else len(body.input.get('asset_ids',[]))
        )
        if body.kind=='video' and ark_video_reference_count>1 and not multimodal:
            raise ValueError('当前火山方舟视频最多接受一张首帧，请移除多余引用')
        if body.kind=='video' and body.input.get('end_asset_id') and ark_video_reference_count!=1:
            raise ValueError('使用火山方舟尾帧时必须同时指定一张首帧')
        if body.kind=='video' and body.input.get('end_asset_id'):
            capabilities=selected['capabilities']
            if capabilities.get('end_frame') is not True:
                raise ValueError('所选火山方舟视频模型不支持尾帧控制')
        if body.kind=='image' and len(references)>max_image_references(selected):
            raise ValueError(f'当前火山方舟图片模型最多支持 {max_image_references(selected)} 张参考图，请移除多余引用')
    if selected and selected.get('type')=='hc_atom':
        if body.kind=='video' and body.input.get('dialogue_audio'):
            from .providers.hc_atom import validate_fixed_dialogue
            validate_fixed_dialogue(selected, body.input, binding.parameters)
        if body.kind=='video' and len(body.input.get('asset_ids',[]))>1 and not multimodal:
            raise ValueError('幻场 AI 通用视频接口最多提交一张参考图')
        if body.kind=='video' and body.input.get('end_asset_id'):
            raise ValueError('幻场 AI 通用视频接口暂未声明尾帧协议，请清除尾帧')
        if body.kind=='image' and len(references)>10:
            raise ValueError('幻场 AI 图片任务最多提交 10 张参考图')
    if selected and selected.get('type')=='runninghub':
        from .providers.runninghub import model_capabilities
        capabilities=selected['capabilities']
        if body.kind=='video' and body.input.get('end_asset_id') and not body.input.get('asset_ids'):
            raise ValueError('RunningHub 尾帧模式必须同时指定首帧')
        maximum=capabilities.get('max_references')
        if body.kind in ('image','video') and maximum is not None and len(body.input.get('asset_ids',[]))>maximum:
            raise ValueError(f'当前 RunningHub 模型最多支持 {maximum} 张参考图')
    for aid in references:
        asset=reference_asset(pid,aid)
        if body.kind in ('image','video') and asset['kind']!='image':raise ValueError('当前图像和视频适配器只接受图像参考素材')
        if selected and selected['type']=='minimax':
            from .minimax_video import first_frame
            first_frame(asset)
    audio_ids=[]
    for field in ('audio_asset_ids','audio_reference_ids','dialogue_audio_asset_ids'):
        items=body.input.get(field,[])
        if not isinstance(items,list) or any(not isinstance(aid,str) for aid in items):
            raise ValueError('音频参考必须是素材 ID 列表')
        audio_ids.extend(items)
    dialogues=body.input.get('dialogue_audio',[])
    if not isinstance(dialogues,list) or any(not isinstance(item,dict) for item in dialogues):
        raise ValueError('对白音频引用无效')
    audio_ids.extend(item.get('assetId') for item in dialogues)
    for aid in audio_ids:
        if not isinstance(aid,str) or reference_asset(pid,aid)['kind']!='audio':
            raise ValueError('对白/音频参考必须属于当前作品且为音频素材')
    dependencies=body.input.get('upstream_job_ids',[])
    if not isinstance(dependencies,list) or any(not isinstance(jid,str) for jid in dependencies):
        raise ValueError('上游任务引用无效')
    for dependency in dependencies:
        if not c.execute('SELECT id FROM jobs WHERE id=%s AND project_id=%s',(dependency,pid)).fetchone():
            raise ValueError('不能引用其他制作集或不存在的上游任务')
    for source in body.input.get('image_reference_sources',[]):
        if not isinstance(source,dict):
            raise ValueError('图像参考来源无效')
        if source.get('type')=='asset':
            if reference_asset(pid,source.get('asset_id'))['kind']!='image':
                raise ValueError('图像参考必须为图像素材')
        elif source.get('type')=='upstream_job':
            if source.get('job_id') not in dependencies:
                raise ValueError('图像来源必须属于本任务的已验证上游')
        else:
            raise ValueError('图像参考来源无效')
    scope='production' if body.input.get('stage') in ('source_analysis','adaptation_generation') else 'episode'
    jid=s.uid('job-'); now=time.time()
    input_hash=job_admission.fingerprint(pid,body,target,binding)
    if binding and binding.image_spec:
        body.input={**body.input,'image_spec':binding.image_spec}
    if binding and body.kind=='video' and body.input.get('generation_mode'):
        body.input={**body.input,'video_spec':{
            **{key:body.input[key] for key in ('generation_mode','reference_manifest','motion_reference',
                'motion_warnings','planned_shot_duration','shot_duration','dialogue_mode','voice_samples') if key in body.input},
            'parameters':binding.parameters}}
    c.execute('''INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated,scope,production_id,workspace_id,actor_user_id,submission_namespace,input_hash)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(jid,body.submission_id,pid,body.node_id,body.kind,'queued',s.dumps(body.input),now,now,scope,owner['production_id'],owner['workspace_id'],actor.user_id,entrypoint,input_hash))
    if binding:
        platform_models.bind_job(c,jid,binding)
    if target:
        c.execute('UPDATE jobs SET collaboration=%s WHERE id=%s',(s.dumps(target),jid))
    job=s.unpack(c.execute('SELECT * FROM jobs WHERE id=%s',(jid,)).fetchone())
    return job

class AudioBatchCreate(StrictBody):
    jobs:list[JobCreate]=Field(min_length=1,max_length=100)

@app.post('/api/projects/{pid}/audio-jobs')
def submit_audio_batch(pid:str,body:AudioBatchCreate):
    project(pid)
    if any(job.kind!='audio' for job in body.jobs):
        raise ValueError('对白批次仅接受音频任务')
    if len({job.submission_id for job in body.jobs})!=len(body.jobs):
        raise ValueError('批次提交标识不能重复')
    with s.db() as c:
        job_admission.lock(c)
        # All validation, frozen bindings and events share one transaction.
        state=read_project_state(c,pid)
        from .object_job_candidates import lock_batch
        lock_batch(c,pid,body.jobs,state)
        results=[create_job_record(c,pid,job,object_state=state,entrypoint='audio-batch') for job in body.jobs]
        for result in results:
            s.event(pid,{'type':'job','id':result['id']},connection=c)
    return {'jobs':results,'count':len(results)}

@app.post('/api/projects/{pid}/jobs')
def submit(pid:str,body:JobCreate):
    model_validation.reject_private_overrides(body.input)
    saved_project=project(pid)
    with s.db() as c:
        project_state=read_project_state(c,pid)
    from .reference_compiler import compile_shot_image_input
    compiler_models=job_admission.compiler_catalog(pid,'job',body.submission_id)
    prepared_input=compile_shot_image_input(
        project_state['episode_document'],body.node_id,body.kind,body.input,
        compiler_models,
        production_context=project_state['production_context'],
    )
    from .video_dialogue import bind_fixed_dialogue_audio, compile_shot_video_input
    selected_provider=next((item for item in compiler_models if item.get('id')==prepared_input.get('model_id')),None)
    prepared_input=compile_shot_video_input(
        project_state['episode_document'],body.node_id,body.kind,prepared_input,
        production_context=project_state['production_context'],
        parameter_rules=(selected_provider or {}).get('rules',{}),
    )
    hc_dialogue=bool(selected_provider and selected_provider.get('type')=='hc_atom'
        and selected_provider.get('capabilities',{}).get('audio_reference'))
    if body.kind=='video' and selected_provider and (selected_provider.get('type') in ('volcengine_ark','runninghub') or hc_dialogue):
        prepared_input=bind_fixed_dialogue_audio(
            project_state['episode_document'],body.node_id,body.kind,prepared_input,
            production_assets(saved_project['production_id'],kind='audio'),
            production_context=project_state['production_context'],
            parameter_rules=selected_provider.get('rules',{}),
            require_canonical=hc_dialogue,
        )
    if body.kind in ('text','storyboard') and prepared_input.get('target_duration') is None:
        prepared_input={**prepared_input,'target_duration':saved_project['document'].get('duration',15)}
    body=body.model_copy(update={'input':prepared_input})
    from .motion_references import compile_motion_input
    body=body.model_copy(update={'input':compile_motion_input(
        project_state['document'],body.node_id,body.kind,body.input,pid,selected_provider)})
    with s.db() as c:
        job_admission.lock(c)
        if body.input.get('reference_compiler'):
            current_revision=c.execute('''SELECT e.revision,p.revision production_revision
                FROM projects e JOIN productions p ON p.id=e.production_id
                WHERE e.id=%s''',(pid,)).fetchone()
            if (
                not current_revision
                or current_revision['revision']!=saved_project['revision']
                or current_revision['production_revision']!=saved_project['production_revision']
            ):
                raise HTTPException(409,'视觉绑定在任务准备期间已更新，请重试生成')
        result=create_job_record(c,pid,body,object_state=project_state)
        s.event(pid,{'type':'job','id':result['id']},connection=c)
    return result


class SourceCreate(StrictBody):
    title:str=Field(min_length=1,max_length=200)
    type:str='manual'
    metadata:dict=Field(default_factory=dict)

class SourceImport(SourceCreate):
    content:str=Field(min_length=1,max_length=20_000_000)

class ChapterCreate(StrictBody):
    title:str=Field(min_length=1,max_length=300)
    content:str=Field(max_length=2_000_000)

class ChapterSave(ChapterCreate):
    revision:int=Field(ge=1)
    assignment_epoch:int=Field(ge=1)

class OwnedRevisionAction(StrictBody):
    revision:int=Field(ge=1)
    assignment_epoch:int=Field(ge=1)

class ChapterTrashCreate(StrictBody):
    chapter_ids:list[str]=Field(min_length=1,max_length=500)
    versions:dict[str,OwnedRevisionAction]

class SourceDelete(StrictBody):
    versions:dict[str,OwnedRevisionAction]

class SourceExtractionCreate(StrictBody):
    project_id:str
    chapter_ids:list[str]=Field(min_length=1,max_length=500)
    model_id:str=Field(min_length=1,max_length=200)
    allow_cloud:bool=False
    submission_id:str=Field(min_length=8,max_length=80)

def source_document_row(production_id,source_id):
    with s.db() as c:
        row=c.execute('''SELECT * FROM source_documents WHERE id=%s AND production_id=%s
            AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='source' AND d.item_id=source_documents.id)''',(source_id,production_id)).fetchone()
    if not row:raise HTTPException(404,'原著文档不存在')
    return s.unpack(row)

@app.get('/api/productions/{production_id}/sources')
def source_documents(production_id:str):
    production(production_id)
    with s.db() as c:
        rows=c.execute('''SELECT d.*,(SELECT COUNT(*) FROM source_chapters c WHERE c.source_id=d.id
            AND NOT EXISTS(SELECT 1 FROM deleted_items dc WHERE dc.kind='chapter' AND dc.item_id=c.id)) chapter_count
            FROM source_documents d WHERE d.production_id=%s
            AND NOT EXISTS(SELECT 1 FROM deleted_items x WHERE x.kind='source' AND x.item_id=d.id)
            ORDER BY d.updated DESC,d.id''',(production_id,)).fetchall()
    return [s.unpack(row) for row in rows]

@app.post('/api/productions/{production_id}/sources')
def create_source_document(production_id:str,body:SourceCreate):
    production(production_id)
    from .source_library import SOURCE_TYPES
    if body.type not in SOURCE_TYPES:raise ValueError('原著类型无效')
    if not body.title.strip():raise ValueError('原著名称不能为空')
    source_id=s.uid('source-');now=time.time()
    with s.db() as c:
        from .owned_content import production_scope
        production_scope(c,production_id,'source_writer',write=True)
        c.execute('INSERT INTO source_documents VALUES(%s,%s,%s,%s,%s,%s,%s)',(
            source_id,production_id,body.type,body.title.strip(),s.dumps(body.metadata),now,now,
        ))
    return source_document_row(production_id,source_id)

@app.post('/api/productions/{production_id}/sources/import')
def import_source_document(production_id:str,body:SourceImport):
    return _import_source(production_id,body)

@app.post('/api/productions/{production_id}/sources/{source_id}/chapters/import')
def import_source_chapters(production_id:str,source_id:str,body:SourceImport):
    return _import_source(production_id,body,source_id)

def _import_source(production_id,body,existing_source_id=None):
    from .source_library import SOURCE_TYPES,split_chapters
    production(production_id)
    if body.type not in SOURCE_TYPES:raise ValueError('原著类型无效')
    if not body.title.strip():raise ValueError('原著名称不能为空')
    chapters=split_chapters(body.content)
    source_id=existing_source_id or s.uid('source-');now=time.time()
    with s.db() as c:
        from .owned_content import production_scope
        production_scope(c,production_id,'source_writer',write=True)
        actor=identity.current().user_id
        from . import business_roles
        assigned_writer=business_roles.default_assignee(c,production_id,'writer',legacy_user_id=actor)
        if existing_source_id:
            source=c.execute('''SELECT id FROM source_documents WHERE id=%s AND production_id=%s
                FOR UPDATE''',(source_id,production_id)).fetchone()
            if not source or c.execute("SELECT 1 FROM deleted_items WHERE kind='source' AND item_id=%s",(source_id,)).fetchone():
                raise HTTPException(404,'原著不存在或已移入回收站')
            production_scope(c,production_id,'editor')
            start=c.execute('SELECT COALESCE(MAX(chapter_no),0)+1 value FROM source_chapters WHERE source_id=%s',(source_id,)).fetchone()['value']
            c.execute('UPDATE source_documents SET updated=%s WHERE id=%s',(now,source_id))
        else:
            start=1
            c.execute('INSERT INTO source_documents VALUES(%s,%s,%s,%s,%s,%s,%s)',(
                source_id,production_id,body.type,body.title.strip(),s.dumps(body.metadata),now,now,
            ))
        first_chapter_id=None
        for number,(title,content) in enumerate(chapters,start):
            chapter_id=s.uid('chapter-')
            if first_chapter_id is None:first_chapter_id=chapter_id
            c.execute('''INSERT INTO source_chapters(id,source_id,chapter_no,title,content,sort_order,
                revision,created,updated,assignee_id,created_by,updated_by)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(
                chapter_id,source_id,number,title,content,number,1,now,now,
                assigned_writer,actor,actor,
            ))
        count=c.execute('''SELECT COUNT(*) value FROM source_chapters sc WHERE source_id=%s
            AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='chapter' AND d.item_id=sc.id)''',(source_id,)).fetchone()['value']
    return {**source_document_row(production_id,source_id),'chapter_count':count,
            'imported_count':len(chapters),'first_chapter_id':first_chapter_id}

@app.delete('/api/productions/{production_id}/sources/{source_id}')
def delete_source_document(production_id:str,source_id:str,body:SourceDelete):
    from . import owned_content as owned
    from . import collaboration_lifecycle as lifecycle
    from . import business_roles
    now=time.time()
    with s.db() as c:
        identity.lock_identity_invariants(c)
        owned.production_scope(c,production_id,write=True)
        business_roles.require_chapter_cleanup(c,production_id)
        source=c.execute('SELECT * FROM source_documents WHERE id=%s AND production_id=%s FOR UPDATE',
                         (source_id,production_id)).fetchone()
        if not source:raise HTTPException(404,'原著不存在')
        if c.execute("SELECT 1 FROM deleted_items WHERE kind='source' AND item_id=%s",(source_id,)).fetchone():
            raise HTTPException(404,'原著已移入回收站')
        live_ids=[row['id'] for row in c.execute('''SELECT sc.id FROM source_chapters sc WHERE sc.source_id=%s
            AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='chapter' AND d.item_id=sc.id) ORDER BY sc.id''',(source_id,))]
        if set(body.versions)!=set(live_ids):raise HTTPException(409,'章节列表已变化，请重新比较后删除')
        business_roles.require_chapter_cleanup(c,production_id)
        for chapter_id in live_ids:
            row=owned.load(c,production_id,'chapter',chapter_id,write=True)
            expected=body.versions[chapter_id]
            owned.authorize(c,row,expected.revision,expected.assignment_epoch)
        active=c.execute('''SELECT COUNT(*) count FROM jobs j
            JOIN projects p ON p.id=j.project_id
            JOIN source_chapters sc ON j.node_id='source-chapter:' || sc.id
            WHERE p.production_id=%s AND sc.source_id=%s AND j.status IN ('queued','running')''',
            (production_id,source_id)).fetchone()['count']
        if active:raise HTTPException(409,f'该原著仍有 {active} 个事件提取任务，请等待任务结束或先取消任务。')
        lifecycle.fence(c,'source',source_id,'trash')
        chapter_ids=[row['id'] for row in c.execute('SELECT id FROM source_chapters WHERE source_id=%s',(source_id,))]
        event_ids=[row['id'] for row in c.execute('''SELECT e.id FROM source_events e
            JOIN source_chapters sc ON sc.id=e.chapter_id WHERE sc.source_id=%s''',(source_id,))]
        c.execute("INSERT INTO deleted_items(kind,item_id,project_id,deleted_at) VALUES('source',%s,%s,%s)",
            (source_id,production_id,now))
        from .adaptation import mark_adaptation_stale
        production_revision=mark_adaptation_stale(c,production_id,chapter_ids=chapter_ids,event_ids=event_ids)
        targets=production_event_targets(c,production_id)
        for target in targets:
            s.event(target,{'type':'source_deleted','id':source_id},connection=c)
            if production_revision is not None:s.event(target,{'type':'production','revision':production_revision},connection=c)
    return {'deleted':source_id,'name':source['title'],'soft':True}

def trash_source_chapters(production_id,chapter_ids,versions):
    from . import owned_content as owned
    from . import business_roles
    from . import collaboration_lifecycle as lifecycle
    production(production_id);now=time.time()
    chapter_ids=list(dict.fromkeys(chapter_ids))
    if set(versions)!=set(chapter_ids):raise HTTPException(422,'必须提供全部所选章节的版本和分配代际')
    with s.db() as c:
        identity.lock_identity_invariants(c)
        business_roles.require_chapter_cleanup(c,production_id)
        for chapter_id in sorted(chapter_ids):
            row=owned.load(c,production_id,'chapter',chapter_id,write=True)
            expected=versions[chapter_id]
            owned.authorize(c,row,expected.revision,expected.assignment_epoch)
        placeholders=','.join('%s' for _ in chapter_ids)
        chapters=c.execute(f'''SELECT sc.*,sd.title source_title FROM source_chapters sc
            JOIN source_documents sd ON sd.id=sc.source_id WHERE sc.id IN ({placeholders}) AND sd.production_id=%s
            AND NOT EXISTS(SELECT 1 FROM deleted_items ds WHERE ds.kind='source' AND ds.item_id=sd.id)
            AND NOT EXISTS(SELECT 1 FROM deleted_items dc WHERE dc.kind='chapter' AND dc.item_id=sc.id)''',
            [*chapter_ids,production_id]).fetchall()
        if len(chapters)!=len(chapter_ids):raise HTTPException(404,'部分章节不存在或已在回收站')
        node_ids=['source-chapter:'+chapter_id for chapter_id in chapter_ids]
        node_placeholders=','.join('%s' for _ in node_ids)
        active=c.execute(f"SELECT COUNT(*) count FROM jobs WHERE node_id IN ({node_placeholders}) AND status IN ('queued','running')",
            node_ids).fetchone()['count']
        if active:raise HTTPException(409,f'所选章节仍有 {active} 个事件提取任务，请等待任务结束或先取消任务。')
        for chapter_id in sorted(chapter_ids):lifecycle.fence(c,'chapter',chapter_id,'trash')
        event_ids=[row['id'] for row in c.execute(
            f'SELECT id FROM source_events WHERE chapter_id IN ({placeholders})',chapter_ids)]
        with c.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO deleted_items(kind,item_id,project_id,deleted_at) VALUES('chapter',%s,%s,%s)",
                [(chapter_id,production_id,now) for chapter_id in chapter_ids],
            )
        from .adaptation import mark_adaptation_stale
        production_revision=mark_adaptation_stale(c,production_id,chapter_ids=chapter_ids,event_ids=event_ids)
        targets=production_event_targets(c,production_id)
        for target in targets:
            s.event(target,{'type':'source_chapters_deleted','ids':chapter_ids},connection=c)
            if production_revision is not None:s.event(target,{'type':'production','revision':production_revision},connection=c)
    return {'deleted':chapter_ids,'count':len(chapter_ids),'soft':True}

@app.post('/api/productions/{production_id}/chapters/trash')
def delete_source_chapter_batch(production_id:str,body:ChapterTrashCreate):
    if len(set(body.chapter_ids))!=len(body.chapter_ids):raise ValueError('不能重复选择同一章节')
    with s.db() as c:
        from . import business_roles
        business_roles.require_chapter_cleanup(c,production_id)
    return trash_source_chapters(production_id,body.chapter_ids,body.versions)

@app.delete('/api/productions/{production_id}/chapters/{chapter_id}')
def delete_source_chapter(production_id:str,chapter_id:str,body:OwnedRevisionAction):
    return trash_source_chapters(production_id,[chapter_id],{chapter_id:body})

@app.get('/api/productions/{production_id}/chapters')
def source_chapters(production_id:str,source_id:str|None=None,q:str=''):
    production(production_id)
    clauses=['d.production_id=%s',"NOT EXISTS(SELECT 1 FROM deleted_items x WHERE x.kind='source' AND x.item_id=d.id)","NOT EXISTS(SELECT 1 FROM deleted_items x WHERE x.kind='chapter' AND x.item_id=c.id)"];params=[production_id]
    if source_id:clauses.append('c.source_id=%s');params.append(source_id)
    if q.strip():clauses.append('(c.title LIKE %s OR c.content LIKE %s)');term='%'+q.strip()+'%';params.extend([term,term])
    with s.db() as c:
        rows=c.execute('''SELECT c.*,d.title source_title,1+(SELECT COUNT(*) FROM source_chapters previous
            WHERE previous.source_id=c.source_id
            AND NOT EXISTS(SELECT 1 FROM deleted_items hidden WHERE hidden.kind='chapter' AND hidden.item_id=previous.id)
            AND (previous.sort_order<c.sort_order OR (previous.sort_order=c.sort_order AND previous.chapter_no<c.chapter_no)
                OR (previous.sort_order=c.sort_order AND previous.chapter_no=c.chapter_no AND previous.id<c.id))) display_no
            FROM source_chapters c
            JOIN source_documents d ON d.id=c.source_id WHERE '''+' AND '.join(clauses)+
            ' ORDER BY d.created,c.sort_order,c.chapter_no',params).fetchall()
    return [dict(row) for row in rows]

@app.post('/api/productions/{production_id}/sources/{source_id}/chapters')
def create_source_chapter(production_id:str,source_id:str,body:ChapterCreate):
    from . import business_roles
    if not body.title.strip():raise ValueError('章节标题不能为空')
    now=time.time()
    with s.db() as c:
        from .owned_content import production_scope
        production_scope(c,production_id,'source_writer',write=True)
        source=c.execute('''SELECT * FROM source_documents WHERE id=%s AND production_id=%s
            AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='source' AND d.item_id=source_documents.id)
            FOR UPDATE''',(source_id,production_id)).fetchone()
        if not source:raise HTTPException(404,'原著文档不存在')
        production_scope(c,production_id,'editor')
        if c.execute("SELECT 1 FROM deleted_items WHERE kind='source' AND item_id=%s",(source_id,)).fetchone():
            raise HTTPException(404,'原著已移入回收站')
        next_no=c.execute('SELECT COALESCE(MAX(chapter_no),0)+1 value FROM source_chapters WHERE source_id=%s',(source_id,)).fetchone()['value']
        chapter_id=s.uid('chapter-')
        actor=identity.current().user_id
        c.execute('''INSERT INTO source_chapters(id,source_id,chapter_no,title,content,sort_order,
            revision,created,updated,assignee_id,created_by,updated_by)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(
            chapter_id,source_id,next_no,body.title.strip(),body.content,next_no,1,now,now,
            business_roles.default_assignee(c,production_id,'writer',legacy_user_id=actor),actor,actor,
        ))
        c.execute('UPDATE source_documents SET updated=%s WHERE id=%s',(now,source_id))
    return next(item for item in source_chapters(production_id,source_id) if item['id']==chapter_id)

@app.put('/api/productions/{production_id}/chapters/{chapter_id}')
def save_source_chapter(production_id:str,chapter_id:str,body:ChapterSave):
    from . import owned_content as owned
    if not body.title.strip():raise ValueError('章节标题不能为空')
    now=time.time()
    with s.db() as c:
        row=owned.load(c,production_id,'chapter',chapter_id,write=True)
        owned.authorize(c,row,body.revision,body.assignment_epoch)
        owned.history_before(c,row,'save')
        c.execute('''UPDATE source_chapters SET title=%s,content=%s,revision=revision+1,
            status='in_progress',updated=%s,updated_by=%s WHERE id=%s''',(
            body.title.strip(),body.content,now,identity.current().user_id,chapter_id,
        ))
        c.execute('UPDATE source_documents SET updated=%s WHERE id=%s',(now,row['source_id']))
        from .adaptation import mark_adaptation_stale
        production_revision=mark_adaptation_stale(c,production_id,chapter_ids=[chapter_id])
        if production_revision is not None:
            targets=production_event_targets(c,production_id)
            for target in targets:s.event(target,{'type':'production','revision':production_revision},connection=c)
        owned.notify(c,owned.load(c,production_id,'chapter',chapter_id),'save')
    return next(item for item in source_chapters(production_id) if item['id']==chapter_id)

@app.get('/api/productions/{production_id}/source-events')
def source_events(production_id:str,chapter_id:str|None=None):
    production(production_id)
    query='''SELECT e.* FROM source_events e
        JOIN source_chapters c ON c.id=e.chapter_id
        JOIN source_documents d ON d.id=c.source_id
        WHERE e.production_id=%s AND NOT EXISTS(
            SELECT 1 FROM deleted_items x WHERE x.kind='source' AND x.item_id=d.id
        ) AND NOT EXISTS(
            SELECT 1 FROM deleted_items x WHERE x.kind='chapter' AND x.item_id=c.id
        )''';params=[production_id]
    if chapter_id:query+=' AND e.chapter_id=%s';params.append(chapter_id)
    query+=' ORDER BY d.created,c.sort_order,c.chapter_no,e.event_order'
    with s.db() as c:rows=c.execute(query,params).fetchall()
    result=[]
    for row in rows:
        item=dict(row)
        item['characters']=json.loads(item['characters'])
        item['continuity']=json.loads(item['continuity'])
        result.append(item)
    return result

@app.get('/api/productions/{production_id}/source-extractions')
def active_source_extractions(production_id:str):
    with s.db() as c:
        from .owned_content import production_scope
        production_scope(c,production_id)
        rows=c.execute("""SELECT DISTINCT sc.id FROM jobs j JOIN source_chapters sc
            ON j.node_id='source-chapter:' || sc.id
            JOIN source_documents d ON d.id=sc.source_id
            WHERE j.production_id=%s AND d.production_id=%s AND j.kind='text'
            AND j.status IN ('queued','running')
            AND NOT EXISTS(SELECT 1 FROM deleted_items x WHERE x.kind='source' AND x.item_id=d.id)
            AND NOT EXISTS(SELECT 1 FROM deleted_items x WHERE x.kind='chapter' AND x.item_id=sc.id)
            ORDER BY sc.id""",(production_id,production_id)).fetchall()
    return {'chapter_ids':[row['id'] for row in rows]}

@app.post('/api/productions/{production_id}/source-extractions')
def extract_source_events(production_id:str,body:SourceExtractionCreate):
    production(production_id)
    if len(set(body.chapter_ids))!=len(body.chapter_ids):raise ValueError('不能重复选择同一章节')
    with s.db() as c:
        job_admission.lock(c)
        collaboration.lock_identity(c)
        from . import owned_content as owned
        owned.production_scope(c,production_id,'editor')
        owner=c.execute('SELECT id FROM projects WHERE id=%s AND production_id=%s',(body.project_id,production_id)).fetchone()
        if not owner:raise ValueError('文本任务必须归属于当前 Production 的 Episode')
        placeholders=','.join('%s' for _ in body.chapter_ids)
        chapters=c.execute(f'''SELECT c.* FROM source_chapters c JOIN source_documents d ON d.id=c.source_id
            WHERE d.production_id=%s AND c.id IN ({placeholders})
            AND NOT EXISTS(SELECT 1 FROM deleted_items x WHERE x.kind='source' AND x.item_id=d.id)
            AND NOT EXISTS(SELECT 1 FROM deleted_items x WHERE x.kind='chapter' AND x.item_id=c.id)''',[production_id,*body.chapter_ids]).fetchall()
        if len(chapters)!=len(body.chapter_ids):raise ValueError('所选章节不存在或不属于当前 Production')
        # Lock the complete batch in stable order before freezing prompts. A
        # mixed-owner batch cannot leave a partial queue behind.
        chapter_map={cid:owned.load(c,production_id,'chapter',cid,write=True) for cid in sorted(body.chapter_ids)}
        for chapter in chapter_map.values():collaboration.editable(c,chapter)
        job_admission.batch_members(c,body.project_id,'source-extraction',body.submission_id,body.chapter_ids)
        created=[]
        for chapter_id in body.chapter_ids:
            chapter=chapter_map[chapter_id]
            job_body=JobCreate(node_id='source-chapter:'+chapter_id,kind='text',
                submission_id=body.submission_id+':'+chapter_id[:24],input={
                    'model_id':body.model_id,'allow_cloud':body.allow_cloud,
                    'stage':'source_analysis','prompt':f'章节标题：{chapter["title"]}\n\n原文：\n{chapter["content"]}',
                    'source_event_extraction':{'productionId':production_id,'chapterId':chapter_id,'chapterRevision':chapter['revision'],
                                               'assignmentEpoch':chapter['assignment_epoch']},
            })
            created.append(create_job_record(c,body.project_id,job_body,entrypoint='source-extraction'))
        for item in created:
            s.event(body.project_id,{'type':'job','id':item['id']},connection=c)
    return {'jobs':created,'count':len(created)}


class AdaptationSave(StrictBody):
    revision:int=Field(ge=1)
    adaptationPlan:dict
    episodePlans:list[dict]=Field(max_length=500)
    monetizationPlan:dict

class RevisionAction(StrictBody):
    revision:int=Field(ge=1)

class TextGenerationCreate(StrictBody):
    project_id:str
    model_id:str=Field(min_length=1,max_length=200)
    allow_cloud:bool=False
    submission_id:str=Field(min_length=8,max_length=100)

class ScriptSave(StrictBody):
    revision:int=Field(ge=0)
    assignment_epoch:int=Field(ge=0)
    title:str
    synopsis:str
    body:str
    estimatedDuration:float
    sourceChapterRefs:list[str]
    storyGoal:str
    paywallBeat:dict
    characters:list[str]
    scenes:list[str]
    props:list[str]
    canvasNodeId:str|None=Field(default=None,min_length=1,max_length=160)

class ScriptGenerationCreate(StrictBody):
    episode_nos:list[int]=Field(min_length=1,max_length=500)
    model_id:str=Field(min_length=1,max_length=200)
    allow_cloud:bool=False
    submission_id:str=Field(min_length=8,max_length=100)

class ScriptAssistCreate(OwnedRevisionAction):
    instruction:str=Field(min_length=1,max_length=24000)
    model_id:str=Field(min_length=1,max_length=200)
    allow_cloud:bool=False
    submission_id:str=Field(min_length=8,max_length=100)

def production_event_targets(connection,production_id):
    return [row['id'] for row in connection.execute('''SELECT p.id FROM projects p
        WHERE p.production_id=%s AND NOT EXISTS(
            SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=p.id
        )''',(production_id,)).fetchall()]

@app.get('/api/productions/{production_id}/adaptation')
def read_adaptation(production_id:str):
    from .adaptation import adaptation_bundle,source_snapshot
    value=production(production_id)
    revision=value['revision'];context=value['context']
    with s.db() as c:
        sources=source_snapshot(c,production_id)
    return {**adaptation_bundle(context),'revision':revision,'sourceEventCount':len(sources)}

@app.put('/api/productions/{production_id}/adaptation')
def save_adaptation(production_id:str,body:AdaptationSave):
    from .owned_content import production_scope
    from .adaptation import (
        _persist_production_context,_stale_scripts,prepare_manual_adaptation,
        validate_source_references,protected_episode_nos,
    )
    with s.db() as c:
        production_scope(c,production_id,'writer',write=True)
        row=c.execute('SELECT * FROM productions WHERE id=%s FOR UPDATE',(production_id,)).fetchone()
        if not row:raise HTTPException(404,'Production 不存在')
        production_scope(c,production_id,'writer')
        if row['revision']!=body.revision:raise HTTPException(409,'改编策划已在其他页面更新，请重新加载。')
        context=normalize_production_context(json.loads(row['shared_context']))
        bundle,changed,shared_changed,changed_episodes=prepare_manual_adaptation(context,{
            'adaptationPlan':body.adaptationPlan,'episodePlans':body.episodePlans,
            'monetizationPlan':body.monetizationPlan,
        })
        protected=set(protected_episode_nos(c,production_id,lock=True))
        if protected.intersection(changed_episodes) or (shared_changed and protected):
            raise HTTPException(409,'已有采纳视频的分集受保护；只能修改其他分集，不能修改全局改编内容')
        validate_source_references(c,production_id,[chapter for plan in bundle['episodePlans'] for chapter in plan['sourceChapterRefs']])
        context.update(bundle)
        if changed:_stale_scripts(c,production_id,episode_nos=None if shared_changed else changed_episodes)
        revision=_persist_production_context(c,row,context)
        targets=production_event_targets(c,production_id)
        for pid in targets:s.event(pid,{'type':'production','revision':revision},connection=c)
    return {**bundle,'revision':revision}

def transition_adaptation(production_id,expected_revision,target,episode_no=None):
    from .owned_content import production_scope
    from .adaptation import _persist_production_context,adaptation_bundle,validate_adaptation_bundle,validate_approval_ready,protected_episode_nos
    with s.db() as c:
        production_scope(c,production_id,'writer',write=True)
        row=c.execute('SELECT * FROM productions WHERE id=%s FOR UPDATE',(production_id,)).fetchone()
        if not row:raise HTTPException(404,'Production 不存在')
        production_scope(c,production_id,'writer')
        if row['revision']!=expected_revision:raise HTTPException(409,'改编策划已在其他页面更新，请重新加载。')
        protected=protected_episode_nos(c,production_id,lock=True)
        if protected and (episode_no is None or episode_no in protected):
            raise HTTPException(409,'已有分集采纳视频，不能整体变更审核状态；请只审核新增分集')
        context=normalize_production_context(json.loads(row['shared_context']))
        bundle=adaptation_bundle(context)
        if episode_no is not None:
            from .adaptation import validate_source_references
            plan=next((item for item in bundle['episodePlans'] if item['episodeNo']==episode_no),None)
            if plan is None:raise HTTPException(404,'分集规划不存在')
            if not plan['sourceChapterRefs'] or any(not str(plan.get(key) or '').strip()
                for key in ('logline','coreConflict','hook','cliffhanger')):
                raise ValueError('请先完成本集规划及原著章节引用并保存')
            validate_source_references(c,production_id,plan['sourceChapterRefs'])
            if target=='approved' and plan['status']!='review':raise ValueError('请先将本集规划提交审核')
            plan['status']=target
        elif target=='review':
            validate_adaptation_bundle(bundle)
            bundle['adaptationPlan']['status']='review'
            for plan in bundle['episodePlans']:plan['status']='review'
        else:
            if bundle['adaptationPlan']['status']!='review':raise ValueError('请先将改编策划提交审核，再批准')
            bundle=validate_approval_ready(c,production_id,bundle)
            bundle['adaptationPlan']['status']='approved'
            for plan in bundle['episodePlans']:plan['status']='approved'
        context.update(bundle)
        revision=_persist_production_context(c,row,context)
        targets=production_event_targets(c,production_id)
        for pid in targets:s.event(pid,{'type':'production','revision':revision},connection=c)
    return {**bundle,'revision':revision}

@app.post('/api/productions/{production_id}/adaptation/review')
def review_adaptation(production_id:str,body:RevisionAction):
    return transition_adaptation(production_id,body.revision,'review')

@app.post('/api/productions/{production_id}/adaptation/approve')
def approve_adaptation(production_id:str,body:RevisionAction):
    return transition_adaptation(production_id,body.revision,'approved')

@app.post('/api/productions/{production_id}/adaptation/episodes/{episode_no}/review')
def review_episode_plan(production_id:str,episode_no:int,body:RevisionAction):
    return transition_adaptation(production_id,body.revision,'review',episode_no)

@app.post('/api/productions/{production_id}/adaptation/episodes/{episode_no}/approve')
def approve_episode_plan(production_id:str,episode_no:int,body:RevisionAction):
    return transition_adaptation(production_id,body.revision,'approved',episode_no)

@app.post('/api/productions/{production_id}/adaptation/episodes/{episode_no}/generate')
def generate_episode_plan(production_id:str,episode_no:int,body:TextGenerationCreate):
    from .owned_content import production_scope
    from .episode_plans import frozen_input
    with s.db() as c:
        job_admission.lock(c)
        production_scope(c,production_id,'writer',write=True)
        c.execute('SELECT id FROM productions WHERE id=%s FOR UPDATE',(production_id,)).fetchone()
        project=collaboration.project_scope(c,body.project_id,'editor')
        if project['production_id']!=production_id:raise HTTPException(422,'任务分集不属于当前作品')
        value=frozen_input(c,body.project_id,episode_no)
        value.update(model_id=body.model_id,allow_cloud=body.allow_cloud)
        result=create_job_record(c,body.project_id,JobCreate(node_id=f'adaptation-episode:{production_id}:{episode_no}',
            kind='text',submission_id=body.submission_id,input=value),entrypoint='adaptation')
        s.event(body.project_id,{'type':'job','id':result['id']},connection=c)
    return result

@app.post('/api/productions/{production_id}/adaptation/generate')
def generate_adaptation(production_id:str,body:TextGenerationCreate):
    from .adaptation import adaptation_fingerprint,source_fingerprint,source_snapshot
    with s.db() as c:
        job_admission.lock(c)
        from . import owned_content as owned
        owned.production_scope(c,production_id,'writer',write=True)
        c.execute('SELECT id FROM productions WHERE id=%s FOR UPDATE',(production_id,)).fetchone()
        state=read_project_state(c,body.project_id)
        if not state or state['project']['production_id']!=production_id:
            raise ValueError('改编任务必须归属于当前 Production 的 Episode')
        sources=source_snapshot(c,production_id)
        if not sources:raise ValueError('请先在原著资料库提取事件，再生成改编策划')
        context=state['production_context'];format_value=context['adaptationPlan']['format']
        episode_count = int(format_value['episodeCount'])
        prompt='''请依据原著事件生成完整改编策划。所有 sourceEventIds/sourceChapterRefs 只能使用输入中已有 ID。
商业字段必须服从总集数：freeEpisodes 范围为 0–{count}；firstPaywallEpisode 范围为 1–{after}，其中 {after} 表示全剧不设付费集；每个付费卡点 episodeNo 范围为 1–{count}。
目标规格：'''.format(count=episode_count, after=episode_count + 1)+s.dumps(format_value)+'\n原著事件：\n'+s.dumps(sources)
        job_body=JobCreate(node_id='adaptation:'+production_id,kind='text',submission_id=body.submission_id,input={
            'model_id':body.model_id,'allow_cloud':body.allow_cloud,
            'stage':'adaptation_generation','prompt':prompt,
            'adaptation_generation':{
                'productionId':production_id,'adaptationFingerprint':adaptation_fingerprint(context),
                'sourceFingerprint':source_fingerprint(sources),'sourceEventIds':[item['id'] for item in sources],
                'sourceChapterIds':list(dict.fromkeys(item['chapterId'] for item in sources)),
                'format':format_value,
            },
        })
        result=create_job_record(c,body.project_id,job_body,entrypoint='adaptation')
        s.event(body.project_id,{'type':'job','id':result['id']},connection=c)
    return result

@app.get('/api/productions/{production_id}/scripts')
def production_scripts(production_id:str):
    from .adaptation import adaptation_bundle,script_to_api
    value=production(production_id);plans=adaptation_bundle(value['context'])['episodePlans']
    with s.db() as c:
        rows=c.execute('''SELECT p.id project_id,p.episode_no,p.episode_title,sc.* FROM projects p
            LEFT JOIN episode_scripts sc ON sc.project_id=p.id
            WHERE p.production_id=%s AND NOT EXISTS(
                SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=p.id
            )''',(production_id,)).fetchall()
    existing={row['episode_no']:row for row in rows}
    result=[]
    plan_map={plan['episodeNo']:plan for plan in plans}
    for number in sorted(set(existing)|set(plan_map)):
        plan=plan_map.get(number);row=existing.get(number)
        result.append({'episodeNo':number,'plan':plan,'projectId':row['project_id'] if row else None,
            'episodeTitle':row['episode_title'] if row else f'第 {number:02d} 集',
            'script':script_to_api(row) if row and row['revision'] is not None else None})
    return result

def episode_plan_context(connection,production_id,episode_no,required=True):
    row=connection.execute('SELECT * FROM productions WHERE id=%s',(production_id,)).fetchone()
    if not row:raise HTTPException(404,'Production 不存在')
    context=normalize_production_context(json.loads(row['shared_context']))
    plan=next((item for item in context['episodePlans'] if item['episodeNo']==episode_no),None)
    if not plan and required:raise HTTPException(404,'分集规划中没有这一集')
    return row,context,plan

@app.get('/api/productions/{production_id}/episode-scripts/{episode_no}')
def read_episode_script(production_id:str,episode_no:int):
    from .adaptation import script_default_from_plan,script_row
    with s.db() as c:
        _,_,plan=episode_plan_context(c,production_id,episode_no,required=False)
        project_row=c.execute('''SELECT p.* FROM projects p WHERE p.production_id=%s AND p.episode_no=%s
            AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=p.id)''',(production_id,episode_no)).fetchone()
        if not project_row:
            if not plan:raise HTTPException(404,'这一集尚未建立')
            return script_default_from_plan(None,plan)
        return script_row(c,project_row['id']) or script_default_from_plan(project_row['id'],plan)

@app.put('/api/productions/{production_id}/episode-scripts/{episode_no}')
def save_episode_script(production_id:str,episode_no:int,body:ScriptSave):
    from . import owned_content as owned
    if body.canvasNodeId:raise HTTPException(410,'画布提升已移至 script-promotion 原子命令，须同时提供节点、结构与剧本版本')
    from .adaptation import ensure_episode_for_plan,save_script_row,script_row,validate_source_references
    with s.db() as c:
        owned.production_scope(c,production_id,'editor',write=True)
        _,_,plan=episode_plan_context(c,production_id,episode_no,required=False)
        existed=c.execute('SELECT id FROM projects WHERE production_id=%s AND episode_no=%s',(production_id,episode_no)).fetchone()
        project_row=ensure_episode_for_plan(c,production_id,episode_no)
        row=owned.load(c,production_id,'script',project_row['id'],write=True)
        initial=not existed and body.revision==0 and body.assignment_epoch==0
        owned.authorize(c,row,row['revision'] if initial else body.revision,
                        row['assignment_epoch'] if initial else body.assignment_epoch)
        payload=body.model_dump(exclude={'revision','assignment_epoch','canvasNodeId'})
        validate_source_references(c,production_id,payload['sourceChapterRefs'])
        saved=save_script_row(c,row,payload,status='draft',actor_id=identity.current().user_id)
        owned.notify(c,owned.load(c,production_id,'script',project_row['id']),'save')
    return saved

def transition_script(production_id,episode_no,expected_revision,assignment_epoch,target):
    from . import owned_content as owned
    from .adaptation import ensure_episode_for_plan,script_row,script_to_api
    with s.db() as c:
        owned.production_scope(c,production_id,'editor',write=True)
        _,context,plan=episode_plan_context(c,production_id,episode_no,required=False)
        project_row=ensure_episode_for_plan(c,production_id,episode_no)
        row=owned.load(c,production_id,'script',project_row['id'],write=True)
        owned.authorize(c,row,expected_revision,assignment_epoch,reviewer=target!='review')
        if target in ('review','approved') and not row['body'].strip():raise ValueError('剧本正文为空，不能提交审核或批准')
        metadata=json.loads(row['metadata'])
        independent=metadata.get('origin')=='canvas' or metadata.get('adaptationLinked') is False
        if target=='approved':
            if not independent and (context['adaptationPlan']['status']!='approved' or not plan or plan['status']!='approved'):raise ValueError('请先批准改编策划和本集分集规划')
            if row['status']!='review':raise ValueError('请先将本集剧本提交审核')
        if target=='review' and row['status']=='stale':raise ValueError('剧本已过期，请先修订后再提交审核')
        now=time.time()
        from .adaptation import _script_snapshot
        c.execute('INSERT INTO episode_script_revisions VALUES(%s,%s,%s,%s,%s)',(
            s.uid('script-revision-'),project_row['id'],row['revision'],s.dumps(_script_snapshot(row)),now,
        ))
        c.execute('UPDATE episode_scripts SET status=%s,revision=revision+1,updated=%s,updated_by=%s WHERE project_id=%s',
                  (target,now,identity.current().user_id,project_row['id']))
        saved=script_row(c,project_row['id'])
        owned.notify(c,owned.load(c,production_id,'script',project_row['id']),'review')
    return saved

@app.post('/api/productions/{production_id}/episode-scripts/{episode_no}/review')
def review_episode_script(production_id:str,episode_no:int,body:OwnedRevisionAction):
    return transition_script(production_id,episode_no,body.revision,body.assignment_epoch,'review')

@app.post('/api/productions/{production_id}/episode-scripts/{episode_no}/approve')
def approve_episode_script(production_id:str,episode_no:int,body:OwnedRevisionAction):
    return transition_script(production_id,episode_no,body.revision,body.assignment_epoch,'approved')

@app.post('/api/productions/{production_id}/episode-scripts/{episode_no}/needs-changes')
def revise_episode_script(production_id:str,episode_no:int,body:OwnedRevisionAction):
    return transition_script(production_id,episode_no,body.revision,body.assignment_epoch,'draft')

@app.post('/api/productions/{production_id}/script-generations')
def generate_episode_scripts(production_id:str,body:ScriptGenerationCreate):
    from .adaptation import ensure_episode_for_plan
    from .script_generations import frozen_input
    if len(set(body.episode_nos))!=len(body.episode_nos):raise ValueError('不能重复选择同一集')
    with s.db() as c:
        job_admission.lock(c)
        from . import owned_content as owned
        owned.production_scope(c,production_id,'editor',write=True)
        c.execute('SELECT id FROM productions WHERE id=%s FOR UPDATE',(production_id,)).fetchone()
        production_row,context,_=episode_plan_context(c,production_id,body.episode_nos[0])
        if context['adaptationPlan']['status']!='approved':raise ValueError('请先批准改编策划，再生成逐集剧本')
        plan_map={item['episodeNo']:item for item in context['episodePlans']}
        created=[]
        batch_project=ensure_episode_for_plan(c,production_id,body.episode_nos[0])
        job_admission.batch_members(c,batch_project['id'],'script-generation',body.submission_id,body.episode_nos)
        for episode_no in body.episode_nos:
            plan=plan_map.get(episode_no)
            if not plan:raise ValueError(f'第 {episode_no:02d} 集不在分集规划中')
            if plan['status']!='approved':raise ValueError(f'第 {episode_no:02d} 集规划尚未批准')
            project_row=ensure_episode_for_plan(c,production_id,episode_no)
            script=owned.load(c,production_id,'script',project_row['id'],write=True)
            collaboration.editable(c,script)
            frozen=frozen_input(c,project_row['id'],production_row,script)
            job_body=JobCreate(node_id='episode-script:'+project_row['id'],kind='text',
                submission_id=body.submission_id+f':{episode_no:03d}',input={
                    'model_id':body.model_id,'allow_cloud':body.allow_cloud,
                    **frozen,
            })
            created.append(create_job_record(c,project_row['id'],job_body,entrypoint='script-generation'))
        for item in created:
            s.event(item['project_id'],{'type':'job','id':item['id']},connection=c)
    return {'jobs':created,'count':len(created)}


@app.post('/api/productions/{production_id}/episode-scripts/{episode_no}/assist')
def assist_episode_script(production_id:str,episode_no:int,body:ScriptAssistCreate):
    from . import owned_content as owned
    from .direct_scripts import checked_context,context_fingerprint,assist_prompt
    with s.db() as c:
        job_admission.lock(c)
        owned.production_scope(c,production_id,'editor',write=True)
        c.execute('SELECT id FROM productions WHERE id=%s FOR UPDATE',(production_id,)).fetchone()
        project_row=c.execute('SELECT id FROM projects WHERE production_id=%s AND episode_no=%s',
                              (production_id,episode_no)).fetchone()
        if not project_row:raise HTTPException(404,'目标分集不存在')
        pid=project_row['id']
        collaboration.project_scope(c,pid,'editor')
        context=checked_context(c,pid)
        row=owned.load(c,production_id,'script',pid,write=True)
        owned.authorize(c,row,body.revision,body.assignment_epoch)
        job_body=JobCreate(node_id='episode-script:'+pid,kind='text',submission_id=body.submission_id,input={
            'model_id':body.model_id,'allow_cloud':body.allow_cloud,'stage':'script_generation',
            'prompt':assist_prompt(context,body.instruction),
            'episode_script_generation':{'mode':'direct','productionId':production_id,'episodeNo':episode_no,
                'scriptRevision':body.revision,'assignmentEpoch':body.assignment_epoch,
                'instruction':body.instruction.strip(),'contextFingerprint':context_fingerprint(context)}})
        job=create_job_record(c,pid,job_body,entrypoint='script-generation')
        s.event(pid,{'type':'job','id':job['id']},connection=c)
        return job

@app.post('/api/projects/{pid}/run')
async def run_workflow(pid:str,request:Request):
    from starlette.concurrency import run_in_threadpool
    body=await request.json()
    # PostgreSQL row waits and synchronous preparation must not block the ASGI
    # loop: other editors need to save/reassign while this request is preparing.
    return await run_in_threadpool(prepare_run_workflow,pid,body)

def prepare_run_workflow(pid,body):
    from .workflows import execution_plan
    model_validation.reject_private_overrides(body)
    p=project(pid)
    with s.db() as c:
        project_state=read_project_state(c,pid)
        from .adaptation import project_script_to_document
        p['document']=project_script_to_document(c,pid,project_state['document'],snapshot=project_state['script'])
    group=body.get('submission_id')
    if not isinstance(group,str) or len(group)<8 or len(group)>80: raise ValueError('批次提交标识无效')
    exact=body.get('exact') is True
    plan=execution_plan(
        p['document'],body.get('node_ids'),body.get('include_descendants') is True,exact,
    )
    providers={x['id']:x for x in job_admission.compiler_catalog(pid,'canvas-run',group,batch=True)}
    # Validate the entire batch before submitting its first runnable node.
    for node,_ in plan:
        data=node.get('data',{})
        if data.get('kind') not in ('text','storyboard','image','video'): continue
        model_validation.reject_private_overrides(data)
        if not providers.get(data.get('model_id')):
            raise ValueError('部分节点未选择可用的平台模型；不会自动回退或切换服务')
    for node,parents in plan:
        data=node.get('data',{})
        if data.get('kind') not in ('text','storyboard','image','video'): continue
        if not data.get('prompt','').strip() and not parents: raise ValueError('起始节点缺少创作描述')
    # A reference node is a static asset rather than a runnable job.  Preserve
    # that asset in the downstream job snapshot, just as the canvas's
    # single-node submit path does.  Runnable image parents are deliberately
    # left to the worker: it substitutes their freshly generated result when
    # the downstream job becomes runnable.
    mapping={
        node['id']:node for node in p['document'].get('nodes',[])
        if not (
            node.get('data',{}).get('managed') is True
            and node.get('data',{}).get('kind')=='visual_asset'
        )
    }
    planned_ids={node['id'] for node,_ in plan}
    runnable={'text','storyboard','image','video'}
    prepared=[]
    from .reference_compiler import compile_shot_image_input
    from .video_dialogue import bind_fixed_dialogue_audio, compile_shot_video_input
    from .visual_references import resolve_image_model_capabilities
    available_audio_assets=production_assets(p['production_id'],kind='audio')
    capability_cache={}
    def cached_image_capabilities(provider,model_id):
        key=(provider.get('id'),model_id)
        if key not in capability_cache:
            capability_cache[key]=resolve_image_model_capabilities(provider,model_id)
        return capability_cache[key]
    for node,parents in plan:
        data=dict(node.get('data',{}));kind=data.get('kind')
        if kind not in runnable: continue
        data=compile_shot_image_input(
            project_state['episode_document'],node['id'],kind,data,
            list(providers.values()),cached_image_capabilities,
            production_context=project_state['production_context'],
        )
        data=compile_shot_video_input(
            project_state['episode_document'],node['id'],kind,data,
            production_context=project_state['production_context'],
            parameter_rules=(providers.get(data.get('model_id')) or {}).get('rules',{}),
        )
        film_bible_compiled=bool(data.get('reference_compiler'))
        manual_assets=list(data.get('asset_ids',[]))
        static_assets=[]
        generated_image_parents=0
        reference_sources=[]
        seen_reference_sources=set()
        for parent_id in ([] if film_bible_compiled else parents):
            parent_data=mapping[parent_id].get('data',{})
            if parent_data.get('kind')=='image':
                dynamic_parent=parent_id in planned_ids
                parent_asset_id=parent_data.get('assetId')
                if dynamic_parent:
                    generated_image_parents+=1
                elif parent_asset_id:
                    static_assets.append(parent_asset_id)
                key=(
                    ('upstream_node',parent_id)
                    if dynamic_parent
                    else ('asset',parent_asset_id)
                )
                if key not in seen_reference_sources:
                    if dynamic_parent:
                        reference_sources.append({'type':'upstream_node','node_id':parent_id})
                    elif parent_asset_id:
                        reference_sources.append({'type':'asset','asset_id':parent_asset_id})
                    seen_reference_sources.add(key)
            if parent_data.get('kind') not in runnable and parent_data.get('assetId'):
                asset_id=parent_data['assetId'];static_assets.append(asset_id)
                key=('asset',asset_id)
                if key not in seen_reference_sources:
                    reference_sources.append({'type':'asset','asset_id':asset_id})
                    seen_reference_sources.add(key)
        for asset_id in manual_assets:
            key=('asset',asset_id)
            if key not in seen_reference_sources:
                reference_sources.append({'type':'asset','asset_id':asset_id})
                seen_reference_sources.add(key)
        data['asset_ids']=(
            manual_assets
            if film_bible_compiled
            else list(dict.fromkeys([*manual_assets,*static_assets]))
        )
        if film_bible_compiled:
            reference_sources=list(data['image_reference_sources'])
            generated_image_parents=0
        for aid in data['asset_ids']:
            reference_asset(pid,aid)
        provider=providers.get(data.get('model_id'))
        from .motion_references import resolve_generation_mode
        from .video_dialogue import _shot_for_video_node
        multimodal=kind=='video' and resolve_generation_mode(p['document'],_shot_for_video_node(p['document'],node['id']))['requested']=='multimodal'
        if provider and provider.get('type')=='volcengine_ark':
            if kind=='video':
                data=bind_fixed_dialogue_audio(
                    project_state['episode_document'],node['id'],kind,data,
                    available_audio_assets,
                    production_context=project_state['production_context'],
                    parameter_rules=provider.get('rules',{}),
                )
            if kind=='video' and 'resolution' in provider.get('rules',{}):
                data['parameters']={
                    'resolution':p['document'].get('videoResolution','720p'),
                    **(data.get('parameters') or {}),
                }
            from .providers.volcengine_ark import max_image_references
            reference_count=len(data['asset_ids'])+generated_image_parents
            if kind=='video' and reference_count>1 and not multimodal:
                raise ValueError('当前火山方舟视频最多接受一张首帧，请只保留一条图像连线或一张素材')
            if kind=='video' and data.get('end_asset_id') and reference_count!=1 and not multimodal:
                raise ValueError('使用火山方舟尾帧时必须同时保留一张首帧')
            if kind=='image' and reference_count>max_image_references(provider):
                raise ValueError(f'当前火山方舟图片模型最多支持 {max_image_references(provider)} 张参考图，请移除多余引用')
        if provider and provider.get('type')=='hc_atom':
            if kind=='video' and provider.get('capabilities',{}).get('audio_reference'):
                data=bind_fixed_dialogue_audio(
                    project_state['episode_document'],node['id'],kind,data,
                    available_audio_assets,
                    production_context=project_state['production_context'],
                    parameter_rules=provider.get('rules',{}), require_canonical=True,
                )
            reference_count=len(data['asset_ids'])+generated_image_parents
            if kind=='video' and reference_count>1 and not multimodal:
                raise ValueError('幻场 AI 通用视频接口最多提交一张参考图')
            if kind=='video' and data.get('end_asset_id') and not multimodal:
                raise ValueError('幻场 AI 通用视频接口暂未声明尾帧协议，请清除尾帧')
            if kind=='image' and reference_count>10:
                raise ValueError('幻场 AI 图片任务最多提交 10 张参考图')
        if provider and provider.get('type')=='runninghub':
            reference_count=len(data['asset_ids'])+generated_image_parents
            maximum=10 if kind=='image' else 30
            if kind in ('image','video') and reference_count>maximum:
                raise ValueError(f'当前 RunningHub {"图片" if kind=="image" else "视频"}模型最多支持 {maximum} 张参考图')
            if kind=='video':
                data=bind_fixed_dialogue_audio(
                    project_state['episode_document'],node['id'],kind,data,
                    available_audio_assets,
                    production_context=project_state['production_context'],
                    parameter_rules=provider.get('rules',{}),
                )
                if 'resolution' in provider.get('rules',{}):
                    data['parameters']={
                        'resolution':p['document'].get('videoResolution','720p'),
                        **(data.get('parameters') or {}),
                    }
        if provider and provider.get('type')=='minimax':
            # Hailuo accepts exactly one initial image.  Detect multiple
            # upstream image branches before any expensive parent job starts.
            if len(data['asset_ids'])+generated_image_parents>1:
                raise ValueError('MiniMax 图生视频仅接受一张首帧；请保留一条图像连线或在节点中选择一张素材')
        from .motion_references import compile_motion_input
        data['image_reference_sources']=reference_sources
        data=compile_motion_input(p['document'],node['id'],kind,data,pid,provider)
        reference_sources=data.get('image_reference_sources',reference_sources)
        if not data.get('prompt','').strip():
            if not parents: raise ValueError(f'节点 {data.get("label",node["id"])} 缺少输入')
            data['prompt']={'text':'根据上游信息编写剧本','storyboard':'将上游剧本拆解为结构化分镜','image':'生成上游描述的电影画面','video':'根据上游画面与描述生成动态镜头'}[kind]
        data['project_style']=p['document'].get('style','')
        if kind=='video' and provider and 'ratio' in provider.get('rules',{}):
            data['ratio']=p['document'].get('videoRatio') or p['document'].get('ratio','16:9')
        # Image aspect is resolved once from canonical state at admission;
        # injecting a second spelling here conflicts with saved parameters.
        if kind in ('text','storyboard'):
            data['target_duration']=data.get('target_duration') or p['document'].get('duration',15)
        if kind=='storyboard':
            data['film_bible']=data.get('film_bible') is not False
        prepared.append((node,parents,data,reference_sources))
    jobs_by_node={};created=[]
    with s.db() as c:
        job_admission.lock(c)
        from .object_job_candidates import lock_batch
        lock_batch(c,pid,[JobCreate(node_id=node['id'],kind=data['kind'],submission_id=f'{group}:{node["id"]}',input=data)
                         for node,_,data,_ in prepared],project_state)
        job_admission.batch_members(c,pid,'canvas-run',group,[node['id'] for node,_,_,_ in prepared])
        if any(data.get('reference_compiler') for _,_,data,_ in prepared):
            current_revision=c.execute('''SELECT e.revision,p.revision production_revision
                FROM projects e JOIN productions p ON p.id=e.production_id
                WHERE e.id=%s''',(pid,)).fetchone()
            if (
                not current_revision
                or current_revision['revision']!=p['revision']
                or current_revision['production_revision']!=p['production_revision']
            ):
                raise HTTPException(409,'视觉绑定在批量任务准备期间已更新，请重试运行')
        for node,parents,data,reference_sources in prepared:
            kind=data.get('kind')
            data['upstream_job_ids']=[jobs_by_node[n] for n in parents if n in jobs_by_node]
            # Film Bible shots already carry compiler-owned asset sources in
            # character/scene/prop order. Other nodes retain canvas-edge order.
            # Dynamic parents are stored by durable job id for the worker.
            data['image_reference_sources']=[
                ({'type':'upstream_job','job_id':jobs_by_node[item['node_id']]}
                 if item['type']=='upstream_node' else item)
                for item in reference_sources
            ]
            result=create_job_record(c,pid,JobCreate(node_id=node['id'],kind=kind,submission_id=f'{group}:{node["id"]}',input=data),object_state=project_state,entrypoint='canvas-run')
            jobs_by_node[node['id']]=result['id'];created.append(result['id'])
        for jid in created:
            s.event(pid,{'type':'job','id':jid},connection=c)
    return {'job_ids':created,'count':len(created)}

@app.get('/api/projects/{pid}/jobs')
def jobs(pid:str):
    project(pid)
    with s.db() as c:
        return [s.unpack(r) for r in c.execute('SELECT * FROM jobs WHERE project_id=%s ORDER BY created DESC LIMIT 200',(pid,))]

@app.get('/api/jobs/{jid}')
def read_job(jid:str):
    with s.db() as c:
        row=c.execute('SELECT * FROM jobs WHERE id=%s',(jid,)).fetchone()
    if not row: raise HTTPException(404,'任务不存在')
    return s.unpack(row)

@app.post('/api/jobs/{jid}/cancel')
def cancel(jid:str):
    job=read_job(jid)
    if job['status'] in ('queued','running','interrupted'):
        s.job_update(jid,control=True,status='cancelled',phase='已请求取消，等待运行引擎释放')
        # Re-read after cancellation so a provider handle attached between the
        # initial read and this state change is visible to remote cancellation.
        job=read_job(jid)
        provider=None
        if job.get('provider_job_id') and job['kind']!='export':
            try:
                with s.db() as c:
                    provider=platform_models.load_job_provider(c,jid,remote=True)
            except ValueError:
                s.cancelled_phase(jid,'本地已取消；原模型凭证/配置不可用，未换账号取消远端任务，请人工核对',control=True)
        from .provider_redaction import protect
        with protect(provider.get('api_key','') if provider else ''), provider_egress.before_call(lambda: platform_models.check_job_call(jid)):
            if provider and provider.get('type')=='replicate':
                from .replicate_api import cancel as cancel_replicate
                cancel_replicate(job,provider)
            elif provider and provider.get('type')=='volcengine_ark':
                from .providers.volcengine_ark import cancel as cancel_ark
                remote_cancelled=cancel_ark(job,provider)
                if remote_cancelled is True:
                    s.cancelled_phase(jid,'已取消本地等待，并已请求供应商取消远端任务',control=True)
                elif remote_cancelled is False:
                    s.cancelled_phase(jid,'本地已取消；供应商可能继续生成并产生费用',control=True)
            elif provider and provider.get('type')=='hc_atom':
                from .providers.hc_atom import cancel as cancel_hc
                remote_cancelled=cancel_hc(job,provider)
                if remote_cancelled is True:
                    s.cancelled_phase(jid,'已取消本地等待，并已请求幻场 AI 取消远端任务',control=True)
                elif remote_cancelled is False:
                    s.cancelled_phase(jid,'本地已取消；幻场 AI 远端任务可能继续生成并产生费用',control=True)
            elif provider and provider.get('type')=='runninghub':
                s.cancelled_phase(jid,'本地已取消；RunningHub 远端任务可能继续生成并产生费用',control=True)
        with s.db() as c:
            scope=c.execute('SELECT workspace_id,production_id FROM jobs WHERE id=%s',(jid,)).fetchone()
            identity.audit(c,'job.cancel','job',jid,workspace_id=scope['workspace_id'],production_id=scope['production_id'])
    return read_job(jid)

@app.post('/api/jobs/{jid}/resume')
def resume(jid:str):
    # Remote jobs keep polling the original handle. Synchronous jobs do not have
    # one, so an explicit resume action requeues their frozen input instead.
    with s.db() as c:
        from . import collaboration as collab
        from .job_candidates import authorize_resume
        collab.lock_identity(c)
        job=c.execute('SELECT * FROM jobs WHERE id=%s FOR UPDATE',(jid,)).fetchone()
        if not job: raise HTTPException(404,'任务不存在')
        collab.project_scope(c,job['project_id'],'editor')
        if job['status'] in ('queued','running','succeeded'): return s.unpack(job)
        if job['status']!='interrupted': raise HTTPException(409,'只有中断任务可以恢复查询')
        authorize_resume(c,s.unpack(job))
        provider=platform_models.load_job_provider(c,jid,remote=bool(job['provider_job_id'])) if job['kind']!='export' else {}
        if job['provider_job_id']:
            if provider.get('type') not in ('maestro','comfy','video_api','minimax','replicate','volcengine_ark','hc_atom','runninghub'):
                raise HTTPException(409,'此任务的上游服务不支持恢复查询，请核对服务配置')
            phase='恢复查询已有上游任务'
        else:
            frozen_input=json.loads(job['input'])
            marker=frozen_input.get('source_event_extraction') or {}
            if marker.get('chapterId'):
                chapter=c.execute('''SELECT sc.id,sd.production_id FROM source_chapters sc
                    JOIN source_documents sd ON sd.id=sc.source_id WHERE sc.id=%s
                    AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='source' AND d.item_id=sd.id)
                    AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='chapter' AND d.item_id=sc.id)''',
                    (marker['chapterId'],)).fetchone()
                if not chapter or chapter['production_id']!=marker.get('productionId'):
                    raise HTTPException(409,'原任务对应的章节已删除或归属已变化，无法重新排队')
            phase='使用已保存的输入重新排队'
        updated=c.execute('''UPDATE jobs SET status='queued',result=NULL,error=NULL,phase=%s,progress=NULL,
            started=NULL,finished=NULL,telemetry=NULL,updated=%s WHERE id=%s AND status='interrupted'
            RETURNING *''',(phase,time.time(),jid)).fetchone()
        if not updated:raise HTTPException(409,'任务状态已变化，不能恢复查询')
        identity.audit(c,'job.resume','job',jid,workspace_id=job['workspace_id'],production_id=job['production_id'])
        s.event(job['project_id'],{'type':'job','id':jid},connection=c)
    return read_job(jid)

EVENT_BACKLOG_LIMIT=500


def _requested_event_id(after=None, last_event_id=None):
    candidates = []
    for value in (after, last_event_id):
        try:
            if value is not None:
                candidates.append(max(0, int(value)))
        except (TypeError, ValueError):
            pass
    return max(candidates) if candidates else None


def _event_cursor(
    latest, after=None, last_event_id=None, backlog_limit=EVENT_BACKLOG_LIMIT, *,
    oldest_retained=None, requested_retained=False, visible_backlog=None,
):
    """Choose an SSE cursor from retained rows, never from identity arithmetic."""
    requested = _requested_event_id(after, last_event_id)
    if requested is None or requested >= latest:
        return latest
    if visible_backlog is None:
        raise ValueError('visible_backlog is required for a reconnect cursor')
    # A missing cursor below the oldest retained row is genuinely outside the
    # retention window. A missing id within the window may only be a sequence
    # gap, so its actual visible backlog still decides the replay policy.
    if oldest_retained is not None and requested < oldest_retained and not requested_retained:
        return latest
    return latest if visible_backlog > backlog_limit else requested


@app.get('/api/events')
async def events(request:Request,after:int|None=None):
    endpoint_principal=identity.current(False)
    async def stream():
        requested = _requested_event_id(after, request.headers.get('last-event-id'))
        with s.db() as c:
            allowed=identity.visible_production_ids(c,endpoint_principal) if endpoint_principal else None
            scope_sql=' AND production_id=ANY(%s)' if allowed is not None else ''
            scope_args=(allowed,) if allowed is not None else ()
            if requested is None:
                latest = c.execute('SELECT COALESCE(MAX(id),0) latest FROM events WHERE TRUE'+scope_sql,scope_args).fetchone()['latest']
                cursor = latest
            else:
                snapshot = c.execute(f'''SELECT
                    COALESCE((SELECT MAX(id) FROM events WHERE TRUE{scope_sql}),0) latest,
                    (SELECT MIN(id) FROM events WHERE TRUE{scope_sql}) oldest_retained,
                    EXISTS(SELECT 1 FROM events WHERE id=%s{scope_sql}) requested_retained,
                    (SELECT COUNT(*) FROM (
                        SELECT id FROM events WHERE id>%s{scope_sql} ORDER BY id LIMIT %s
                    ) visible) visible_backlog''',(
                    *scope_args,*scope_args,requested,*scope_args,
                    requested,*scope_args,EVENT_BACKLOG_LIMIT+1,
                )).fetchone()
                cursor = _event_cursor(
                    snapshot['latest'],after,request.headers.get('last-event-id'),
                    oldest_retained=snapshot['oldest_retained'],
                    requested_retained=snapshot['requested_retained'],
                    visible_backlog=snapshot['visible_backlog'],
                )
        while not await request.is_disconnected():
            if endpoint_principal and identity.resolve_session(request) is None:
                break
            with s.db() as c:
                allowed=identity.visible_production_ids(c,endpoint_principal) if endpoint_principal else None
                if allowed is not None:
                    rows=c.execute('''SELECT * FROM events WHERE id>%s AND production_id=ANY(%s)
                        ORDER BY id LIMIT 100''',(cursor,allowed)).fetchall()
                else:
                    rows=c.execute('SELECT * FROM events WHERE id>%s ORDER BY id LIMIT 100',(cursor,)).fetchall()
            for row in rows:
                cursor=row['id']
                yield f'id: {cursor}\ndata: {s.dumps({"project_id":row["project_id"],**json.loads(row["payload"])})}\n\n'
            if not rows: yield ': heartbeat\n\n'
            await asyncio.sleep(2)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no'})

if (s.ROOT/'dist').is_dir():
    @app.get('/admin',include_in_schema=False)
    def admin_page():
        return FileResponse(s.ROOT/'dist'/'index.html')

    @app.get('/members',include_in_schema=False)
    def members_page():
        return FileResponse(s.ROOT/'dist'/'index.html')

    app.mount('/',StaticFiles(directory=s.ROOT/'dist',html=True),name='web')
