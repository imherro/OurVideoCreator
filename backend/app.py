import asyncio
import hashlib
import hmac
import json
import mimetypes
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, Request, Response, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import store as s
from .instance_identity import describe as describe_instance
from .prompts import TEMPLATES
from .generation_policy import default_ark_policy, validate_generation_policy
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

app = FastAPI(title='安影 AI 视频工作室',lifespan=lifespan,docs_url=None,redoc_url=None)
PUBLIC = {'/api/health','/api/auth/status','/api/auth/setup','/api/auth/login'}

@app.middleware('http')
async def auth(request: Request, call_next):
    if request.url.path.startswith('/api/'):
        # Cookie-authenticated mutations must originate from this deployment.
        origin = request.headers.get('origin')
        if request.method not in ('GET','HEAD','OPTIONS') and origin and urlparse(origin).netloc != request.headers.get('host'):
            return Response('跨站请求已拒绝',status_code=403)
        signed_provider_asset = request.method in ('GET','HEAD') and request.url.path.startswith('/api/provider-assets/')
        if request.url.path not in PUBLIC and not signed_provider_asset:
            token = request.cookies.get('mvc_session','')
            with s.db() as c:
                row = c.execute('SELECT expires FROM sessions WHERE token=%s',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
            if not row or row['expires'] < time.time():
                return Response(s.dumps({'detail':'请登录工作室'}),401,media_type='application/json')
    result = await call_next(request)
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
    token = hashlib.sha256(request.cookies.get('mvc_session','').encode()).hexdigest()
    with s.db() as c:
        row = c.execute('SELECT expires FROM sessions WHERE token=%s',(token,)).fetchone()
    return {'configured':bool(s.get_setting('password')),'authenticated':bool(row and row['expires']>time.time()),'can_setup':True}

class Password(BaseModel):
    password: str = Field(min_length=8,max_length=128)

def password_hash(password,salt):
    return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()

def session(response, request):
    token = secrets.token_urlsafe(48)
    with s.db() as c:
        c.execute('DELETE FROM sessions WHERE expires<%s',(time.time(),))
        c.execute('INSERT INTO sessions VALUES(%s,%s)',(hashlib.sha256(token.encode()).hexdigest(),time.time()+7*86400))
    response.set_cookie('mvc_session',token,max_age=7*86400,httponly=True,samesite='strict',secure=request.url.scheme=='https')

@app.post('/api/auth/setup')
def setup(body:Password,request:Request,response:Response):
    salt = secrets.token_hex(16)
    encoded = s.dumps({'salt':salt,'hash':password_hash(body.password,salt)})
    with s.db() as c:
        if c.execute('SELECT 1 FROM settings WHERE key=%s',('password',)).fetchone():
            raise HTTPException(409,'工作室已经设置密码，请登录。')
        c.execute('INSERT INTO settings VALUES(%s,%s)',('password',encoded))
    session(response,request)
    return {'ok':True}

_attempts = {}
@app.post('/api/auth/login')
def login(body:Password,request:Request,response:Response):
    ip = request.client.host
    attempts = [t for t in _attempts.get(ip,[]) if t > time.time()-300]
    if len(attempts)>=10:
        raise HTTPException(429,'尝试次数过多，请五分钟后重试。')
    saved = s.get_setting('password')
    if not saved or not hmac.compare_digest(password_hash(body.password,saved['salt']),saved['hash']):
        _attempts[ip] = attempts+[time.time()]
        raise HTTPException(401,'密码不正确')
    _attempts.pop(ip,None)
    session(response,request)
    return {'ok':True}

@app.post('/api/auth/logout')
def logout(request:Request,response:Response):
    with s.db() as c:
        c.execute('DELETE FROM sessions WHERE token=%s',(hashlib.sha256(request.cookies.get('mvc_session','').encode()).hexdigest(),))
    response.delete_cookie('mvc_session')
    return {'ok':True}

def project(pid):
    with s.db() as c:
        row = c.execute("SELECT * FROM projects WHERE id=%s AND NOT EXISTS(SELECT 1 FROM deleted_items WHERE kind='project' AND item_id=projects.id)",(pid,)).fetchone()
        state=read_project_state(c,pid) if row else None
    if not row:
        raise HTTPException(404,'项目不存在')
    value=s.unpack(row)
    value['document']=state['document']
    value['production_revision']=state['production']['revision']
    from .generation_staleness import reconcile_generation_staleness
    value['document']=reconcile_generation_staleness(
        state['episode_document'],s.get_setting('providers',[]),
        production_context=state['production_context'],
    )
    from .adaptation import project_script_to_document
    with s.db() as c:
        value['document']=project_script_to_document(c,pid,value['document'])
    return value

@app.get('/api/projects')
def projects():
    with s.db() as c:
        return [dict(r) for r in c.execute("SELECT id,name,revision,created,updated,production_id,episode_no,episode_title FROM projects WHERE NOT EXISTS(SELECT 1 FROM deleted_items WHERE kind='project' AND item_id=projects.id) ORDER BY updated DESC")]

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
    return value

@app.get('/api/productions')
def productions():
    with s.db() as c:
        return [dict(row) for row in c.execute('''SELECT p.id,p.name,p.revision,p.created,p.updated,
            (SELECT COUNT(*) FROM projects e WHERE e.production_id=p.id AND NOT EXISTS(
                SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=e.id
            )) episode_count
            FROM productions p
            WHERE NOT EXISTS(
                SELECT 1 FROM projects e WHERE e.production_id=p.id
            ) OR EXISTS(
                SELECT 1 FROM projects e WHERE e.production_id=p.id AND NOT EXISTS(
                    SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=e.id
                )
            )
            ORDER BY p.updated DESC''')]

class ProductionCreate(BaseModel):
    name:str=Field(default='未命名剧集',max_length=100)

class ProductionUpdate(BaseModel):
    revision:int=Field(ge=1)
    name:str=Field(max_length=100)

@app.post('/api/productions')
def create_production(body:ProductionCreate):
    production_id=s.uid('production-')
    now=time.time();name=normalized_project_name(body.name)
    context=new_production_context(default_ark_policy(s.get_setting('providers',[])))
    with s.db() as c:
        c.execute('INSERT INTO productions(id,name,revision,shared_context,created,updated) VALUES(%s,%s,1,%s,%s,%s)',(production_id,name,s.dumps(context),now,now))
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
        episodes=c.execute('''SELECT id,episode_no,episode_title,document FROM projects
            WHERE production_id=%s AND NOT EXISTS(
                SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=projects.id
            ) ORDER BY episode_no,id''',(production_id,)).fetchall()
    for episode in episodes:
        document=json.loads(episode['document'])
        for shot in document.get('shots') or []:
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

class EpisodeCreate(BaseModel):
    title:str=Field(default='',max_length=100)

@app.post('/api/productions/{production_id}/episodes')
def create_episode(production_id:str,body:EpisodeCreate):
    document=new_document(default_ark_policy(s.get_setting('providers',[])))
    now=time.time();pid=s.uid('project-')
    with s.db() as c:
        parent=c.execute('SELECT * FROM productions WHERE id=%s FOR UPDATE',(production_id,)).fetchone()
        if not parent:raise HTTPException(404,'Production 不存在')
        episode_no=c.execute(
            'SELECT COALESCE(MAX(episode_no),0)+1 value FROM projects WHERE production_id=%s',
            (production_id,),
        ).fetchone()['value']
        title=body.title.strip() or f'第 {episode_no:02d} 集'
        c.execute('''INSERT INTO projects(
            id,name,revision,document,created,updated,production_id,episode_no,episode_title
        ) VALUES(%s,%s,1,%s,%s,%s,%s,%s,%s)''',(
            pid,title,s.dumps(episode_document_from_document(document)),now,now,production_id,episode_no,title,
        ))
        c.execute('UPDATE productions SET updated=%s WHERE id=%s',(now,production_id))
        from .adaptation import seed_episode_scripts
        seed_episode_scripts(c)
    return project(pid)

class ProjectCreate(BaseModel):
    name:str=Field(default='未命名短片',max_length=100)
    episode_title:str|None=Field(default=None,max_length=100)
    style:str|None=Field(default=None,max_length=200)
    ratio:str|None=None
    duration:float|None=Field(default=None,ge=5,le=3000)
    video_resolution:str=Field(default='720p')
    video_ratio:str=Field(default='16:9')
    video_duration:int=Field(default=-1)
    video_format:str=Field(default='mp4')
    episode_count:int=Field(default=1,ge=1,le=500)
    platform:str=Field(default='通用短视频',min_length=1,max_length=100)
    brief:str|None=Field(default=None,max_length=24000)
    generation_policy:dict|None=None
    film_bible:dict|None=None

def normalized_project_name(name:str)->str:
    return name.strip() or '未命名短片'

def project_create_document(body:ProjectCreate):
    providers=s.get_setting('providers',[])
    document=new_document(default_ark_policy(providers))
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
    if body.brief is not None:document['brief']=body.brief
    if body.generation_policy is not None:
        document['generationPolicy']=validate_generation_policy(
            body.generation_policy,providers,allow_missing=False,
        )
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
        c.execute('INSERT INTO productions(id,name,revision,shared_context,created,updated) VALUES(%s,%s,1,%s,%s,%s)',(production_id,name,s.dumps(context),now,now))
        c.execute('''INSERT INTO projects(
            id,name,revision,document,created,updated,production_id,episode_no,episode_title
        ) VALUES(%s,%s,1,%s,%s,%s,%s,1,%s)''',(pid,episode_title,s.dumps(episode_document_from_document(document)),now,now,production_id,episode_title))
        from .adaptation import seed_episode_scripts
        seed_episode_scripts(c)
    return project(pid)

@app.get('/api/projects/{pid}')
def read_project(pid:str):
    return project(pid)

@app.delete('/api/projects/{pid}')
def delete_project(pid:str):
    with s.db() as c:
        row=c.execute("SELECT * FROM projects WHERE id=%s AND NOT EXISTS(SELECT 1 FROM deleted_items WHERE kind='project' AND item_id=projects.id)",(pid,)).fetchone()
        if not row: raise HTTPException(404,'项目不存在')
        active=c.execute("SELECT COUNT(*) count FROM jobs WHERE project_id=%s AND status IN ('queued','running')",(pid,)).fetchone()['count']
        if active: raise HTTPException(409,f'项目仍有 {active} 个运行中任务，请先取消后再移入回收站。')
        c.execute("INSERT INTO deleted_items(kind,item_id,project_id,deleted_at) VALUES('project',%s,%s,%s)",(pid,pid,time.time()))
    return {'deleted':pid,'soft':True}

@app.get('/api/projects/{pid}/storyboard-sheet')
def storyboard_sheet(pid:str,columns:int=3,page:int=1):
    from .contact_sheet import render_sheet
    return Response(render_sheet(project(pid),columns,page),media_type='image/png',headers={'Content-Disposition':f'attachment; filename="storyboard-{page}.png"'})

class ProjectSave(BaseModel):
    name:str=Field(max_length=100)
    revision:int
    production_revision:int|None=None
    document:dict

@app.put('/api/projects/{pid}')
def save_project(pid:str,body:ProjectSave):
    document=migrate_document(body.document)
    # Preserve deleted provider ids so ordinary project edits remain savable;
    # the resolver reports the invalid target before any generation starts.
    document['generationPolicy']=validate_generation_policy(document['generationPolicy'],s.get_setting('providers',[]),allow_missing=True)
    projected_context=production_context_from_document(document)
    with s.db() as c:
        state=read_project_state(c,pid,for_update=True)
        if not state: raise HTTPException(404,'项目不存在')
        old=state['project'];production_row=state['production']
        incoming_context={
            **state['production_context'],
            **{key:projected_context[key] for key in SHARED_DOCUMENT_KEYS},
        }
        if old['revision']!=body.revision: raise HTTPException(409,'项目已在其他页面更新，请重新加载后编辑。')
        from .adaptation import project_script_to_document
        episode_document=episode_document_from_document(
            project_script_to_document(c,pid,document)
        )
        encoded_episode=s.dumps(episode_document)
        if len(encoded_episode)>8_000_000:
            raise HTTPException(413,'项目数据过大，请将素材上传到素材库。')
        shared_changed=incoming_context!=state['production_context']
        # Phase 1A clients do not know the Production revision yet. Allow their
        # first shared-context save while the Production is still at revision 1;
        # every later shared edit must carry the independent revision token.
        episode_count = c.execute(
            'SELECT COUNT(*) count FROM projects WHERE production_id=%s',
            (old['production_id'],),
        ).fetchone()['count']
        compatible_production_revision = (
            production_row['revision']
            if (
                body.production_revision is None
                and episode_count == 1
                and production_row['revision'] == 1
            )
            else body.production_revision
        )
        if shared_changed and compatible_production_revision!=production_row['revision']:
            raise HTTPException(409,'Production 共享资料已在其他页面更新，请重新加载后编辑。')
        from .film_bible.versioning import validate_film_bible_transition
        before_shots=[];after_shots=[]
        for episode in c.execute(
            'SELECT id,document FROM projects WHERE production_id=%s ORDER BY episode_no,id',
            (old['production_id'],),
        ):
            previous_episode=migrate_document(json.loads(episode['document']))
            before_shots.extend(previous_episode.get('shots') or [])
            current_episode=episode_document if episode['id']==pid else previous_episode
            after_shots.extend(current_episode.get('shots') or [])
        before_validation={**state['document'],'shots':before_shots}
        after_validation={**document,'shots':after_shots}
        validate_film_bible_transition(before_validation,after_validation)
        updated=time.time()
        c.execute('INSERT INTO revisions VALUES(%s,%s,%s,%s,%s)',(
            s.uid(),pid,old['revision'],s.dumps(state['document']),updated,
        ))
        name=normalized_project_name(body.name)
        updated_project=c.execute(
            'UPDATE projects SET name=%s,episode_title=%s,revision=revision+1,document=%s,updated=%s '
            'WHERE id=%s AND revision=%s RETURNING revision',
            (name,name,encoded_episode,updated,pid,body.revision),
        ).fetchone()
        if not updated_project:
            raise HTTPException(409,'项目已在其他页面更新，请重新加载后编辑。')
        production_revision=production_row['revision']
        if shared_changed:
            c.execute('INSERT INTO production_revisions(id,production_id,revision,shared_context,created) VALUES(%s,%s,%s,%s,%s)',(
                s.uid(),old['production_id'],production_revision,production_row['shared_context'],updated,
            ))
            production_revision+=1
            updated_production=c.execute(
                'UPDATE productions SET revision=%s,shared_context=%s,updated=%s '
                'WHERE id=%s AND revision=%s RETURNING revision',
                (production_revision,s.dumps(incoming_context),updated,old['production_id'],compatible_production_revision),
            ).fetchone()
            if not updated_production:
                raise HTTPException(409,'Production 共享资料已在其他页面更新，请重新加载后编辑。')
        else:
            c.execute('UPDATE productions SET updated=%s WHERE id=%s',(updated,old['production_id']))
        s.event(pid,{'type':'project','revision':body.revision+1},connection=c)
    return {
        'revision':body.revision+1,
        'production_revision':production_revision,
        'updated':updated,
    }

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
        public['provider_id']=job_input.get('provider')
        public['model_id']=job_input.get('model')
        public['generation_fingerprint']=metadata.get('generationFingerprint')
        visual=job_input.get('visual_reference') or {}
        if isinstance(visual,dict):public['visual_version_id']=visual.get('versionId')
    return public

ASSET_CATEGORIES={'character','scene','prop','shot','music','sfx','voice','reference','other'}
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
async def upload(pid:str,file:UploadFile=File(...),category:str='other'):
    owner=project(pid)
    category=asset_category(category)
    name=Path(file.filename or 'asset').name
    ext=Path(name).suffix.lower()
    allowed={'.png':'image','.jpg':'image','.jpeg':'image','.webp':'image','.mp4':'video','.webm':'video','.mov':'video','.wav':'audio','.mp3':'audio','.m4a':'audio','.srt':'subtitle'}
    if ext not in allowed: raise HTTPException(400,'支持 PNG/JPG/WebP、MP4/WebM/MOV、WAV/MP3/M4A、SRT')
    aid=s.uid('asset-'); path=s.asset_path(aid,ext); total=0
    try:
        with path.open('wb') as out:
            while chunk:=await file.read(1024*1024):
                total+=len(chunk)
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
        with s.db() as c:
            c.execute('INSERT INTO assets(id,project_id,name,kind,path,mime,metadata,created,category,source,production_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(aid,pid,name,allowed[ext],path.name,mimetypes.guess_type(name)[0] or 'application/octet-stream',s.dumps(metadata),time.time(),category,'uploaded',owner['production_id']))
        return asset_public(asset_row(aid))
    except Exception:
        path.unlink(missing_ok=True)
        raise

class AssetUpdate(BaseModel):
    category:str

@app.patch('/api/projects/{pid}/assets/{aid}')
def update_asset(pid:str,aid:str,body:AssetUpdate):
    category=asset_category(body.category)
    reference_asset(pid,aid)
    with s.db() as c:
        c.execute('UPDATE assets SET category=%s WHERE id=%s',(category,aid))
    return asset_public(asset_row(aid))

@app.delete('/api/projects/{pid}/assets/{aid}')
def delete_asset(pid:str,aid:str):
    project(pid)
    row=reference_asset(pid,aid)
    with s.db() as c:
        c.execute("INSERT INTO deleted_items(kind,item_id,project_id,deleted_at) VALUES('asset',%s,%s,%s)",(aid,row['project_id'],time.time()))
        episode_ids=[item['id'] for item in c.execute('SELECT id FROM projects WHERE production_id=%s',(row['production_id'],))]
        for episode_id in episode_ids:s.event(episode_id,{'type':'asset_deleted','id':aid},connection=c)
    return {'deleted':aid,'soft':True}

@app.get('/api/trash')
def trash():
    with s.db() as c:
        deleted_projects=[dict(row) for row in c.execute("SELECT p.id,p.name,d.deleted_at FROM deleted_items d JOIN projects p ON p.id=d.item_id WHERE d.kind='project' ORDER BY d.deleted_at DESC")]
        deleted_assets=[dict(row) for row in c.execute("SELECT a.id,a.name,a.kind,a.category,a.project_id,a.production_id,p.name project_name,d.deleted_at FROM deleted_items d JOIN assets a ON a.id=d.item_id JOIN projects p ON p.id=a.project_id WHERE d.kind='asset' ORDER BY d.deleted_at DESC")]
        deleted_sources=[dict(row) for row in c.execute('''SELECT sd.id,sd.title name,sd.type,
            sd.production_id,p.name production_name,
            (SELECT COUNT(*) FROM source_chapters sc WHERE sc.source_id=sd.id AND NOT EXISTS(
                SELECT 1 FROM deleted_items dc WHERE dc.kind='chapter' AND dc.item_id=sc.id
            )) chapter_count,
            d.deleted_at
            FROM deleted_items d JOIN source_documents sd ON sd.id=d.item_id
            JOIN productions p ON p.id=sd.production_id
            WHERE d.kind='source' ORDER BY d.deleted_at DESC''')]
        deleted_chapters=[dict(row) for row in c.execute('''SELECT sc.id,sc.title name,sc.chapter_no,
            sd.id source_id,sd.title source_name,sd.production_id,p.name production_name,d.deleted_at
            FROM deleted_items d JOIN source_chapters sc ON sc.id=d.item_id
            JOIN source_documents sd ON sd.id=sc.source_id JOIN productions p ON p.id=sd.production_id
            WHERE d.kind='chapter' ORDER BY d.deleted_at DESC''')]
    return {'projects':deleted_projects,'assets':deleted_assets,'sources':deleted_sources,'chapters':deleted_chapters}

@app.post('/api/trash/{kind}/{item_id}/restore')
def restore_deleted_item(kind:str,item_id:str):
    if kind not in ('project','asset','source','chapter'):raise HTTPException(400,'回收站类型无效')
    with s.db() as c:
        row=c.execute('SELECT * FROM deleted_items WHERE kind=%s AND item_id=%s',(kind,item_id)).fetchone()
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
        for episode_id in episode_ids:s.event(episode_id,{'type':'restored','kind':kind,'id':item_id},connection=c)
    return {'restored':item_id,'kind':kind}

@app.get('/api/assets/{aid}/file')
def asset_file(aid:str):
    row=asset_row(aid)
    path=s.stored_asset_path(row['path'])
    if not path.is_relative_to(s.ASSETS) or not path.is_file(): raise HTTPException(404,'素材文件丢失')
    return FileResponse(path,media_type=row['mime'],filename=row['name'],content_disposition_type='inline')

@app.get('/api/provider-assets/{aid}')
def provider_asset_file(aid:str,expires:int,signature:str):
    from .provider_assets import valid_signature
    if not valid_signature(aid,expires,signature):
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
    value=s.get_setting('providers',[])
    return {
        'providers':[
            {**{k:v for k,v in p.items() if k not in ('api_key','auto_start')},'api_key_set':bool(p.get('api_key'))}
            for p in value
        ],
        'ffmpeg':s.get_setting('ffmpeg','ffmpeg'),
    }

@app.put('/api/settings')
async def update_settings(request:Request):
    body=await request.json()
    if 'providers' in body:
        old={p['id']:p for p in s.get_setting('providers',[])}
        for p in body['providers']:
            masked_key_set=bool(p.pop('api_key_set',False))
            p.pop('auto_start',None)
            if not p.get('id') or p.get('type') not in ('openai','comfy','maestro','video_api','minimax','replicate','volcengine_ark','volcengine_speech','hc_atom','runninghub'): raise ValueError('模型服务配置无效')
            if p.get('type')=='volcengine_ark':
                from .providers.volcengine_ark import DEFAULT_BASE_URL
                p['url']=p.get('url') or DEFAULT_BASE_URL
                # Ark is always a paid remote provider.  Do not trust a client
                # supplied `local` flag to bypass the cloud confirmation gate.
                p['local']=False
                p.pop('kind',None)
                if not isinstance(p.get('models'),dict):raise ValueError('火山方舟模型配置无效')
            if p.get('type')=='volcengine_speech':
                from .providers.volcengine_speech import DEFAULT_RESOURCE_ID, DEFAULT_URL
                p['url']=p.get('url') or DEFAULT_URL
                p['local']=False
                p['kind']='audio'
                p['resource_id']=str(p.get('resource_id') or DEFAULT_RESOURCE_ID).strip()
            if p.get('type')=='hc_atom':
                from .providers.hc_atom import DEFAULT_BASE_URL
                p['url']=p.get('url') or DEFAULT_BASE_URL
                p['local']=False
                p.pop('kind',None)
                if not isinstance(p.get('models'),dict):raise ValueError('幻场 AI 模型配置无效')
                public_base_url=str(p.get('public_base_url') or '').strip().rstrip('/')
                if public_base_url:
                    parsed_public=urlparse(public_base_url)
                    if parsed_public.scheme not in ('http','https') or not parsed_public.netloc or parsed_public.username:
                        raise ValueError('幻场 AI 公网素材地址必须是有效的 HTTP(S) 地址')
                    p['public_base_url']=public_base_url
            if p.get('type')=='runninghub':
                from .providers.runninghub import DEFAULT_BASE_URL
                p['url']=p.get('url') or DEFAULT_BASE_URL
                p['local']=False
                p.pop('kind',None)
                if not isinstance(p.get('models'),dict):raise ValueError('RunningHub 模型配置无效')
            url=p.get('url','')
            if urlparse(url).scheme not in ('http','https') or urlparse(url).username: raise ValueError('请输入 HTTP(S) 服务地址')
            # A masked settings round-trip may omit the key or send an empty
            # field with api_key_set=true.  Both mean "keep the saved key".
            if 'api_key' not in p or (not p.get('api_key') and masked_key_set):
                p['api_key']=old.get(p['id'],{}).get('api_key','')
        s.set_setting('providers',body['providers'])
    for key in ('ffmpeg',):
        if key in body: s.set_setting(key,body[key])
    return settings()

@app.get('/api/providers/{provider_id}/models')
def provider_models(provider_id:str,kind:str|None=None):
    import httpx
    provider=next((p for p in s.get_setting('providers',[]) if p['id']==provider_id),None)
    if not provider: raise ValueError('模型服务不存在')
    headers={'Authorization':'Bearer '+provider['api_key']} if provider.get('api_key') else {}
    url=provider['url'].rstrip('/')
    if provider['type']=='volcengine_ark':
        from .providers.volcengine_ark import list_models
        models=list_models(provider)
        if kind in ('text','image','video'):
            models=[model for model in models if model['kind']==kind]
        return {'models':models,'status':'ready'}
    if provider['type']=='hc_atom':
        from .providers.hc_atom import list_models
        models=list_models(provider)
        if kind in ('text','image','video'):
            models=[model for model in models if model['kind']==kind]
        return {'models':models,'status':'ready'}
    if provider['type']=='runninghub':
        from .providers.runninghub import list_models
        models=list_models(provider)
        if kind in ('text','image','video'):
            models=[model for model in models if model['kind']==kind]
        return {'models':models,'status':'ready'}
    try:
        with httpx.Client(timeout=20,trust_env=not provider.get('local'),headers=headers) as client:
            if provider['type']=='maestro':
                response=client.get(url+'/api/v1/models'); response.raise_for_status()
                value=response.json()
                from .capabilities import maestro_model
                models=[maestro_model(m) for m in value.get('models',[])]
                return {'models':[m for m in models if provider.get('kind') in m['kinds'] or not provider.get('kind')]}
            if provider['type']=='openai':
                response=client.get(url+'/models'); response.raise_for_status()
                return {'models':[{'id':m['id'],'name':m.get('name',m['id'])} for m in response.json().get('data',[])]}
            if provider['type']=='comfy':
                response=client.get(url+'/system_stats'); response.raise_for_status()
                return {'models':[{'id':provider.get('model') or 'workflow','name':provider.get('name','ComfyUI 工作流')}],'status':'ready'}
            return {'models':[{'id':provider.get('model',''),'name':provider.get('model','配置的视频模型')}]}
    except httpx.HTTPError as exc:
        raise HTTPException(502,'模型服务连接失败，请确认服务地址、启动状态和密钥') from exc

@app.post('/api/providers/{provider_id}/verify')
def verify_provider(provider_id:str):
    provider=next((p for p in s.get_setting('providers',[]) if p['id']==provider_id),None)
    if provider and provider.get('type')=='volcengine_speech':
        from .providers.volcengine_speech import verify
        return verify(provider)
    if provider and provider.get('type')=='runninghub':
        from .providers.runninghub import verify
        return verify(provider)
    if not provider or provider.get('type') not in ('volcengine_ark','hc_atom'):raise ValueError('统一模型服务配置不存在')
    if provider.get('type')=='hc_atom':
        from .providers.hc_atom import list_models
        service='幻场 AI'
    else:
        from .providers.volcengine_ark import list_models
        service='ARK'
    models=list_models(provider)
    counts={kind:sum(model['kind']==kind for model in models) for kind in ('text','image','video')}
    return {'status':'ready','message':f'{service} API Key 鉴权通过，读取到 {len(models)} 个适用模型','models':models,'counts':counts}

@app.post('/api/providers/{provider_id}/test')
def test_provider(provider_id:str,kind:str='text'):
    provider=next((p for p in s.get_setting('providers',[]) if p['id']==provider_id),None)
    if not provider or provider.get('type') not in ('volcengine_ark','hc_atom','runninghub'):raise ValueError('统一模型服务配置不存在')
    if provider.get('type')=='runninghub':
        from .providers.runninghub import check_configured_model
    elif provider.get('type')=='hc_atom':
        from .providers.hc_atom import check_configured_model
    else:
        from .providers.volcengine_ark import check_configured_model
    return check_configured_model(provider,kind)

class JobCreate(BaseModel):
    node_id:str
    kind:str
    submission_id:str=Field(min_length=8,max_length=200)
    input:dict

class PromptTemplateSave(BaseModel):
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
    return s.get_setting('prompt_library',{'revision':0,'templates':[]})

@app.put('/api/prompt-library/{tid}')
def save_prompt_template(tid:str,body:PromptTemplateSave):
    if len(tid)>100 or body.kind not in ('text','storyboard','image','video'):raise ValueError('模板类型或编号无效')
    with s.db() as c:
        c.execute("""INSERT INTO settings(key,value) VALUES('prompt_library',%s)
            ON CONFLICT(key) DO NOTHING""",(s.dumps({'revision':0,'templates':[]}),))
        row=c.execute("SELECT value FROM settings WHERE key='prompt_library' FOR UPDATE").fetchone()
        library=json.loads(row['value'])
        if library['revision']!=body.revision:raise HTTPException(409,'模板库已在另一页面更新，请刷新后保存；当前草稿仍保留')
        old=next((t for t in library['templates'] if t['id']==tid),None)
        history=old.get('history',[]) if old else []
        if old:history=[{k:v for k,v in old.items() if k!='history'},*history][:20]
        template={'id':tid,'name':body.name,'kind':body.kind,'content':body.content,'deleted':body.deleted,'version':old['version']+1 if old else 1,'updated':time.time(),'history':history}
        library['templates']=[template,*[t for t in library['templates'] if t['id']!=tid]]
        if len(library['templates'])>500:raise ValueError('模板库最多保存 500 个模板')
        library['revision']+=1
        c.execute("UPDATE settings SET value=%s WHERE key='prompt_library'",(s.dumps(library),))
    return library

def create_job_record(c,pid,body):
    from .job_contracts import freeze_prompt_contract
    body.input=freeze_prompt_contract(body.kind,body.input)
    if body.kind not in ('text','storyboard','image','video','audio','export'): raise ValueError('不支持的任务类型')
    old=c.execute('SELECT * FROM jobs WHERE submission_id=%s',(body.submission_id,)).fetchone()
    if old:
        if old['project_id']!=pid: raise HTTPException(409,'提交标识冲突')
        if old['node_id']!=body.node_id or old['kind']!=body.kind or json.loads(old['input'])!=body.input:
            raise HTTPException(409,'同一提交标识不能对应不同输入')
        return s.unpack(old)
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
            body.input,s.get_setting('providers',[]),
        )
    provider_id=str(body.input.get('provider') or '').strip()
    if body.kind!='export' and (not provider_id or provider_id=='local'):
        raise ValueError('未配置外部模型服务，请先选择已连接的 Provider；系统不会自动回退到本地或其他付费模型')
    selected = None
    if body.kind!='export':
        configured={p['id']:p for p in s.get_setting('providers',[])}
        selected=configured.get(provider_id)
        if not selected: raise ValueError('所选外部模型服务未配置；系统不会自动切换到其他服务')
        if selected.get('type') in ('volcengine_ark','hc_atom','runninghub'):
            # Defend jobs created from settings saved by an older build.
            selected={**selected,'local':False}
        if selected.get('kind') and selected['kind']!=('text' if body.kind=='storyboard' else body.kind):raise ValueError('模型服务用途与节点不匹配，请选择适用服务')
        if body.kind=='audio' and selected.get('type')!='volcengine_speech':raise ValueError('角色对白请选择豆包语音服务')
        if selected.get('type')=='volcengine_ark':
            from .providers.volcengine_ark import model_for
            if not model_for(selected,body.kind):raise ValueError('请先配置火山方舟对应类型的模型 ID')
        if selected.get('type')=='hc_atom':
            from .providers.hc_atom import model_for
            if not model_for(selected,body.kind):raise ValueError('请先配置幻场 AI 对应类型的模型 ID')
        if selected.get('type')=='runninghub':
            from .providers.runninghub import model_for
            if not model_for(selected,body.kind):raise ValueError('请先配置 RunningHub 对应类型的模型')
    if selected and selected['type']=='minimax':
        from .minimax_video import payload
        if body.kind!='video':raise ValueError('MiniMax 原生服务仅支持视频节点')
        payload(body.input,selected)
    references=list(body.input.get('asset_ids',[]))
    if body.input.get('end_asset_id'):references.append(body.input['end_asset_id'])
    if selected and selected.get('type')=='volcengine_ark':
        from .providers.volcengine_ark import max_image_references, model_capabilities
        ark_video_reference_count=(
            len(body.input['image_reference_sources'])
            if 'image_reference_sources' in body.input
            else len(body.input.get('asset_ids',[]))
        )
        if body.kind=='video' and ark_video_reference_count>1:
            raise ValueError('当前火山方舟视频最多接受一张首帧，请移除多余引用')
        if body.kind=='video' and body.input.get('end_asset_id') and ark_video_reference_count!=1:
            raise ValueError('使用火山方舟尾帧时必须同时指定一张首帧')
        if body.kind=='video' and body.input.get('end_asset_id'):
            capabilities=model_capabilities(selected,'video',body.input.get('model'))
            if capabilities.get('end_frame') is not True:
                raise ValueError('所选火山方舟视频模型不支持尾帧控制')
        if body.kind=='image' and len(references)>max_image_references(selected):
            raise ValueError(f'当前火山方舟图片模型最多支持 {max_image_references(selected)} 张参考图，请移除多余引用')
    if selected and selected.get('type')=='hc_atom':
        if body.kind=='video' and len(body.input.get('asset_ids',[]))>1:
            raise ValueError('幻场 AI 通用视频接口最多提交一张参考图')
        if body.kind=='video' and body.input.get('end_asset_id'):
            raise ValueError('幻场 AI 通用视频接口暂未声明尾帧协议，请清除尾帧')
        if body.kind=='image' and len(references)>10:
            raise ValueError('幻场 AI 图片任务最多提交 10 张参考图')
    if selected and selected.get('type')=='runninghub':
        from .providers.runninghub import model_capabilities
        capabilities=model_capabilities(selected,body.kind,body.input.get('model'))
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
    owner=c.execute('SELECT production_id FROM projects WHERE id=%s',(pid,)).fetchone()
    if not owner:raise HTTPException(404,'制作集不存在')
    scope='production' if body.input.get('stage') in ('source_analysis','adaptation_generation') else 'episode'
    jid=s.uid('job-'); now=time.time()
    c.execute('''INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated,scope,production_id)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(jid,body.submission_id,pid,body.node_id,body.kind,'queued',s.dumps(body.input),now,now,scope,owner['production_id']))
    if selected:
        c.execute('INSERT INTO job_private VALUES(%s,%s)',(jid,s.dumps(selected)))
    return s.unpack(c.execute('SELECT * FROM jobs WHERE id=%s',(jid,)).fetchone())

@app.post('/api/projects/{pid}/jobs')
def submit(pid:str,body:JobCreate):
    saved_project=project(pid)
    with s.db() as c:
        project_state=read_project_state(c,pid)
    from .reference_compiler import compile_shot_image_input
    prepared_input=compile_shot_image_input(
        project_state['episode_document'],body.node_id,body.kind,body.input,
        s.get_setting('providers',[]),
        production_context=project_state['production_context'],
    )
    from .video_dialogue import bind_fixed_dialogue_audio, compile_shot_video_input
    prepared_input=compile_shot_video_input(
        project_state['episode_document'],body.node_id,body.kind,prepared_input,
        production_context=project_state['production_context'],
    )
    selected_provider=next((item for item in s.get_setting('providers',[]) if item.get('id')==prepared_input.get('provider')),None)
    if body.kind=='video' and selected_provider and selected_provider.get('type') in ('volcengine_ark','runninghub'):
        prepared_input=bind_fixed_dialogue_audio(
            project_state['episode_document'],body.node_id,body.kind,prepared_input,
            production_assets(saved_project['production_id'],kind='audio'),
            production_context=project_state['production_context'],
        )
    if body.kind in ('text','storyboard') and prepared_input.get('target_duration') is None:
        prepared_input={**prepared_input,'target_duration':saved_project['document'].get('duration',15)}
    body=body.model_copy(update={'input':prepared_input})
    tracking = None
    with s.db() as c:
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
        result=create_job_record(c,pid,body)
        if body.input.get('visual_reference') is not None:
            from .visual_references import record_visual_reference_submission
            tracking=record_visual_reference_submission(c,pid,body,result)
        if tracking:
            s.event(pid,{
                'type':'production',
                'revision':tracking['production_revision'],
            },connection=c)
        s.event(pid,{'type':'job','id':result['id']},connection=c)
    if tracking:
        result={
            **result,
            'project_revision':tracking['revision'],
            'production_revision':tracking['production_revision'],
            'project_document':tracking['document'],
        }
    return result


class SourceCreate(BaseModel):
    title:str=Field(min_length=1,max_length=200)
    type:str='manual'
    metadata:dict=Field(default_factory=dict)

class SourceImport(SourceCreate):
    content:str=Field(min_length=1,max_length=20_000_000)

class ChapterCreate(BaseModel):
    title:str=Field(min_length=1,max_length=300)
    content:str=Field(max_length=2_000_000)

class ChapterSave(ChapterCreate):
    revision:int=Field(ge=1)

class ChapterTrashCreate(BaseModel):
    chapter_ids:list[str]=Field(min_length=1,max_length=500)

class SourceExtractionCreate(BaseModel):
    project_id:str
    chapter_ids:list[str]=Field(min_length=1,max_length=500)
    provider:str
    model:str
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
        c.execute('INSERT INTO source_documents VALUES(%s,%s,%s,%s,%s,%s,%s)',(
            source_id,production_id,body.type,body.title.strip(),s.dumps(body.metadata),now,now,
        ))
    return source_document_row(production_id,source_id)

@app.post('/api/productions/{production_id}/sources/import')
def import_source_document(production_id:str,body:SourceImport):
    from .source_library import SOURCE_TYPES,split_chapters
    production(production_id)
    if body.type not in SOURCE_TYPES:raise ValueError('原著类型无效')
    if not body.title.strip():raise ValueError('原著名称不能为空')
    chapters=split_chapters(body.content)
    source_id=s.uid('source-');now=time.time()
    with s.db() as c:
        c.execute('INSERT INTO source_documents VALUES(%s,%s,%s,%s,%s,%s,%s)',(
            source_id,production_id,body.type,body.title.strip(),s.dumps(body.metadata),now,now,
        ))
        for number,(title,content) in enumerate(chapters,1):
            c.execute('INSERT INTO source_chapters VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(
                s.uid('chapter-'),source_id,number,title,content,number,1,now,now,
            ))
    return {**source_document_row(production_id,source_id),'chapter_count':len(chapters)}

@app.delete('/api/productions/{production_id}/sources/{source_id}')
def delete_source_document(production_id:str,source_id:str):
    source=source_document_row(production_id,source_id)
    now=time.time()
    with s.db() as c:
        active=c.execute('''SELECT COUNT(*) count FROM jobs j
            JOIN projects p ON p.id=j.project_id
            JOIN source_chapters sc ON j.node_id='source-chapter:' || sc.id
            WHERE p.production_id=%s AND sc.source_id=%s AND j.status IN ('queued','running')''',
            (production_id,source_id)).fetchone()['count']
        if active:raise HTTPException(409,f'该原著仍有 {active} 个事件提取任务，请等待任务结束或先取消任务。')
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

def trash_source_chapters(production_id,chapter_ids):
    production(production_id);now=time.time()
    chapter_ids=list(dict.fromkeys(chapter_ids))
    with s.db() as c:
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
    return trash_source_chapters(production_id,body.chapter_ids)

@app.delete('/api/productions/{production_id}/chapters/{chapter_id}')
def delete_source_chapter(production_id:str,chapter_id:str):
    return trash_source_chapters(production_id,[chapter_id])

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
    if not body.title.strip():raise ValueError('章节标题不能为空')
    now=time.time()
    with s.db() as c:
        source=c.execute('''SELECT * FROM source_documents WHERE id=%s AND production_id=%s
            AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='source' AND d.item_id=source_documents.id)
            FOR UPDATE''',(source_id,production_id)).fetchone()
        if not source:raise HTTPException(404,'原著文档不存在')
        next_no=c.execute('SELECT COALESCE(MAX(chapter_no),0)+1 value FROM source_chapters WHERE source_id=%s',(source_id,)).fetchone()['value']
        chapter_id=s.uid('chapter-')
        c.execute('INSERT INTO source_chapters VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(
            chapter_id,source_id,next_no,body.title.strip(),body.content,next_no,1,now,now,
        ))
        c.execute('UPDATE source_documents SET updated=%s WHERE id=%s',(now,source_id))
    return next(item for item in source_chapters(production_id,source_id) if item['id']==chapter_id)

@app.put('/api/productions/{production_id}/chapters/{chapter_id}')
def save_source_chapter(production_id:str,chapter_id:str,body:ChapterSave):
    if not body.title.strip():raise ValueError('章节标题不能为空')
    now=time.time()
    with s.db() as c:
        row=c.execute('''SELECT c.*,d.production_id FROM source_chapters c JOIN source_documents d ON d.id=c.source_id
            WHERE c.id=%s AND NOT EXISTS(SELECT 1 FROM deleted_items x WHERE x.kind='source' AND x.item_id=d.id)
            AND NOT EXISTS(SELECT 1 FROM deleted_items x WHERE x.kind='chapter' AND x.item_id=c.id)
            FOR UPDATE OF c''',(chapter_id,)).fetchone()
        if not row or row['production_id']!=production_id:raise HTTPException(404,'章节不存在')
        if row['revision']!=body.revision:raise HTTPException(409,'章节已在其他页面更新，请重新加载。')
        c.execute('UPDATE source_chapters SET title=%s,content=%s,revision=revision+1,updated=%s WHERE id=%s',(
            body.title.strip(),body.content,now,chapter_id,
        ))
        c.execute('UPDATE source_documents SET updated=%s WHERE id=%s',(now,row['source_id']))
        from .adaptation import mark_adaptation_stale
        production_revision=mark_adaptation_stale(c,production_id,chapter_ids=[chapter_id])
        if production_revision is not None:
            targets=production_event_targets(c,production_id)
            for target in targets:s.event(target,{'type':'production','revision':production_revision},connection=c)
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

@app.post('/api/productions/{production_id}/source-extractions')
def extract_source_events(production_id:str,body:SourceExtractionCreate):
    production(production_id)
    if len(set(body.chapter_ids))!=len(body.chapter_ids):raise ValueError('不能重复选择同一章节')
    with s.db() as c:
        owner=c.execute('SELECT id FROM projects WHERE id=%s AND production_id=%s',(body.project_id,production_id)).fetchone()
        if not owner:raise ValueError('文本任务必须归属于当前 Production 的 Episode')
        placeholders=','.join('%s' for _ in body.chapter_ids)
        chapters=c.execute(f'''SELECT c.* FROM source_chapters c JOIN source_documents d ON d.id=c.source_id
            WHERE d.production_id=%s AND c.id IN ({placeholders})
            AND NOT EXISTS(SELECT 1 FROM deleted_items x WHERE x.kind='source' AND x.item_id=d.id)
            AND NOT EXISTS(SELECT 1 FROM deleted_items x WHERE x.kind='chapter' AND x.item_id=c.id)''',[production_id,*body.chapter_ids]).fetchall()
        if len(chapters)!=len(body.chapter_ids):raise ValueError('所选章节不存在或不属于当前 Production')
        chapter_map={row['id']:row for row in chapters};created=[]
        for chapter_id in body.chapter_ids:
            chapter=chapter_map[chapter_id]
            job_body=JobCreate(node_id='source-chapter:'+chapter_id,kind='text',
                submission_id=body.submission_id+':'+chapter_id[:24],input={
                    'provider':body.provider,'model':body.model,
                    'stage':'source_analysis','prompt':f'章节标题：{chapter["title"]}\n\n原文：\n{chapter["content"]}',
                    'source_event_extraction':{'productionId':production_id,'chapterId':chapter_id,'chapterRevision':chapter['revision']},
            })
            created.append(create_job_record(c,body.project_id,job_body))
        for item in created:
            s.event(body.project_id,{'type':'job','id':item['id']},connection=c)
    return {'jobs':created,'count':len(created)}


class AdaptationSave(BaseModel):
    revision:int=Field(ge=1)
    adaptationPlan:dict
    episodePlans:list[dict]=Field(max_length=500)
    monetizationPlan:dict

class RevisionAction(BaseModel):
    revision:int=Field(ge=1)

class TextGenerationCreate(BaseModel):
    project_id:str
    provider:str
    model:str=''
    submission_id:str=Field(min_length=8,max_length=100)

class ScriptSave(BaseModel):
    revision:int=Field(ge=0)
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

class ScriptGenerationCreate(BaseModel):
    episode_nos:list[int]=Field(min_length=1,max_length=500)
    provider:str
    model:str=''
    submission_id:str=Field(min_length=8,max_length=100)

def production_event_targets(connection,production_id):
    return [row['id'] for row in connection.execute('''SELECT p.id FROM projects p
        WHERE p.production_id=%s AND NOT EXISTS(
            SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=p.id
        )''',(production_id,)).fetchall()]

@app.get('/api/productions/{production_id}/adaptation')
def read_adaptation(production_id:str):
    from .adaptation import (
        _persist_production_context,adaptation_bundle,configure_adaptation_format,
        has_legacy_default_format,source_snapshot,
    )
    value=production(production_id)
    revision=value['revision'];context=value['context'];targets=[]
    with s.db() as c:
        if has_legacy_default_format(context):
            episodes=c.execute('''SELECT document FROM projects p WHERE p.production_id=%s
                AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=p.id)
                ORDER BY p.episode_no,p.id''',(production_id,)).fetchall()
            episode_document=json.loads(episodes[0]['document']) if episodes else {}
            context.update(configure_adaptation_format(
                context,max(1,len(episodes)),episode_document.get('duration',15),
                episode_document.get('ratio','16:9'),'通用短视频',
            ))
            row=c.execute('SELECT * FROM productions WHERE id=%s',(production_id,)).fetchone()
            revision=_persist_production_context(c,row,context)
            targets=production_event_targets(c,production_id)
        sources=source_snapshot(c,production_id)
        for target in targets:s.event(target,{'type':'production','revision':revision},connection=c)
    return {**adaptation_bundle(context),'revision':revision,'sourceEventCount':len(sources)}

@app.put('/api/productions/{production_id}/adaptation')
def save_adaptation(production_id:str,body:AdaptationSave):
    from .adaptation import (
        _persist_production_context,_stale_scripts,prepare_manual_adaptation,
        validate_source_references,
    )
    with s.db() as c:
        row=c.execute('SELECT * FROM productions WHERE id=%s FOR UPDATE',(production_id,)).fetchone()
        if not row:raise HTTPException(404,'Production 不存在')
        if row['revision']!=body.revision:raise HTTPException(409,'改编策划已在其他页面更新，请重新加载。')
        context=normalize_production_context(json.loads(row['shared_context']))
        bundle,changed=prepare_manual_adaptation(context,{
            'adaptationPlan':body.adaptationPlan,'episodePlans':body.episodePlans,
            'monetizationPlan':body.monetizationPlan,
        })
        validate_source_references(c,production_id,[chapter for plan in bundle['episodePlans'] for chapter in plan['sourceChapterRefs']])
        context.update(bundle)
        if changed:_stale_scripts(c,production_id)
        revision=_persist_production_context(c,row,context)
        targets=production_event_targets(c,production_id)
        for pid in targets:s.event(pid,{'type':'production','revision':revision},connection=c)
    return {**bundle,'revision':revision}

def transition_adaptation(production_id,expected_revision,target):
    from .adaptation import _persist_production_context,adaptation_bundle,validate_adaptation_bundle,validate_approval_ready
    with s.db() as c:
        row=c.execute('SELECT * FROM productions WHERE id=%s FOR UPDATE',(production_id,)).fetchone()
        if not row:raise HTTPException(404,'Production 不存在')
        if row['revision']!=expected_revision:raise HTTPException(409,'改编策划已在其他页面更新，请重新加载。')
        context=normalize_production_context(json.loads(row['shared_context']))
        bundle=adaptation_bundle(context)
        if target=='review':
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

@app.post('/api/productions/{production_id}/adaptation/generate')
def generate_adaptation(production_id:str,body:TextGenerationCreate):
    from .adaptation import adaptation_fingerprint,source_fingerprint,source_snapshot
    with s.db() as c:
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
            'provider':body.provider,'model':body.model,
            'stage':'adaptation_generation','prompt':prompt,'max_tokens':12000,
            'adaptation_generation':{
                'productionId':production_id,'adaptationFingerprint':adaptation_fingerprint(context),
                'sourceFingerprint':source_fingerprint(sources),'sourceEventIds':[item['id'] for item in sources],
                'sourceChapterIds':list(dict.fromkeys(item['chapterId'] for item in sources)),
                'format':format_value,
            },
        })
        result=create_job_record(c,body.project_id,job_body)
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
    for plan in plans:
        row=existing.get(plan['episodeNo'])
        result.append({'episodeNo':plan['episodeNo'],'plan':plan,'projectId':row['project_id'] if row else None,
            'episodeTitle':row['episode_title'] if row else f'第 {plan["episodeNo"]:02d} 集',
            'script':script_to_api(row) if row and row['revision'] is not None else None})
    return result

def episode_plan_context(connection,production_id,episode_no):
    row=connection.execute('SELECT * FROM productions WHERE id=%s',(production_id,)).fetchone()
    if not row:raise HTTPException(404,'Production 不存在')
    context=normalize_production_context(json.loads(row['shared_context']))
    plan=next((item for item in context['episodePlans'] if item['episodeNo']==episode_no),None)
    if not plan:raise HTTPException(404,'分集规划中没有这一集')
    return row,context,plan

@app.get('/api/productions/{production_id}/episode-scripts/{episode_no}')
def read_episode_script(production_id:str,episode_no:int):
    from .adaptation import script_default_from_plan,script_row
    with s.db() as c:
        _,_,plan=episode_plan_context(c,production_id,episode_no)
        project_row=c.execute('''SELECT p.* FROM projects p WHERE p.production_id=%s AND p.episode_no=%s
            AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=p.id)''',(production_id,episode_no)).fetchone()
        if not project_row:return script_default_from_plan(None,plan)
        return script_row(c,project_row['id']) or script_default_from_plan(project_row['id'],plan)

@app.put('/api/productions/{production_id}/episode-scripts/{episode_no}')
def save_episode_script(production_id:str,episode_no:int,body:ScriptSave):
    from .adaptation import ensure_episode_for_plan,save_script_row,script_row,validate_source_references
    with s.db() as c:
        _,_,plan=episode_plan_context(c,production_id,episode_no)
        existed=c.execute('SELECT id FROM projects WHERE production_id=%s AND episode_no=%s',(production_id,episode_no)).fetchone()
        project_row=ensure_episode_for_plan(c,production_id,episode_no)
        row=c.execute('SELECT * FROM episode_scripts WHERE project_id=%s FOR UPDATE',(project_row['id'],)).fetchone()
        compatible_revision=row['revision'] if not existed and body.revision==0 else body.revision
        if row['revision']!=compatible_revision:raise HTTPException(409,'本集剧本已在其他页面更新，请重新加载。')
        payload=body.model_dump(exclude={'revision','canvasNodeId'})
        validate_source_references(c,production_id,payload['sourceChapterRefs'])
        saved=save_script_row(c,row,payload,status='draft')
        if body.canvasNodeId:
            document=json.loads(project_row['document'])
            source_node=next((node for node in document.get('nodes',[]) if node.get('id')==body.canvasNodeId),None)
            if not source_node or source_node.get('data',{}).get('kind')!='text':
                raise ValueError('画布剧本节点不存在或类型无效')
            metadata=json.loads(row['metadata'])
            metadata.update({'origin':'canvas','projectionNodeId':body.canvasNodeId})
            c.execute('UPDATE episode_scripts SET metadata=%s WHERE project_id=%s',(s.dumps(metadata),project_row['id']))
            saved=script_row(c,project_row['id'])
        s.event(project_row['id'],{'type':'script','revision':saved['revision']},connection=c)
    return saved

def transition_script(production_id,episode_no,expected_revision,target):
    from .adaptation import ensure_episode_for_plan,script_row,script_to_api
    with s.db() as c:
        _,context,plan=episode_plan_context(c,production_id,episode_no)
        project_row=ensure_episode_for_plan(c,production_id,episode_no)
        row=c.execute('SELECT * FROM episode_scripts WHERE project_id=%s FOR UPDATE',(project_row['id'],)).fetchone()
        if row['revision']!=expected_revision:raise HTTPException(409,'本集剧本已在其他页面更新，请重新加载。')
        if target in ('review','approved') and not row['body'].strip():raise ValueError('剧本正文为空，不能提交审核或批准')
        quick_canvas=json.loads(row['metadata']).get('origin')=='canvas'
        if target=='approved':
            if not quick_canvas and (context['adaptationPlan']['status']!='approved' or plan['status']!='approved'):raise ValueError('请先批准改编策划和本集分集规划')
            if row['status']!='review':raise ValueError('请先将本集剧本提交审核')
        if target=='review' and row['status']=='stale':raise ValueError('剧本已过期，请先修订后再提交审核')
        now=time.time()
        from .adaptation import _script_snapshot
        c.execute('INSERT INTO episode_script_revisions VALUES(%s,%s,%s,%s,%s)',(
            s.uid('script-revision-'),project_row['id'],row['revision'],s.dumps(_script_snapshot(row)),now,
        ))
        c.execute('UPDATE episode_scripts SET status=%s,revision=revision+1,updated=%s WHERE project_id=%s',(target,now,project_row['id']))
        saved=script_row(c,project_row['id'])
        s.event(project_row['id'],{'type':'script','revision':saved['revision']},connection=c)
    return saved

@app.post('/api/productions/{production_id}/episode-scripts/{episode_no}/review')
def review_episode_script(production_id:str,episode_no:int,body:RevisionAction):
    return transition_script(production_id,episode_no,body.revision,'review')

@app.post('/api/productions/{production_id}/episode-scripts/{episode_no}/approve')
def approve_episode_script(production_id:str,episode_no:int,body:RevisionAction):
    return transition_script(production_id,episode_no,body.revision,'approved')

@app.post('/api/productions/{production_id}/episode-scripts/{episode_no}/needs-changes')
def revise_episode_script(production_id:str,episode_no:int,body:RevisionAction):
    return transition_script(production_id,episode_no,body.revision,'draft')

@app.post('/api/productions/{production_id}/script-generations')
def generate_episode_scripts(production_id:str,body:ScriptGenerationCreate):
    from .adaptation import adaptation_fingerprint,ensure_episode_for_plan,script_to_api,validate_source_references
    if len(set(body.episode_nos))!=len(body.episode_nos):raise ValueError('不能重复选择同一集')
    with s.db() as c:
        production_row,context,_=episode_plan_context(c,production_id,body.episode_nos[0])
        if context['adaptationPlan']['status']!='approved':raise ValueError('请先批准改编策划，再生成逐集剧本')
        plan_map={item['episodeNo']:item for item in context['episodePlans']}
        fingerprint=adaptation_fingerprint(context);created=[]
        for episode_no in body.episode_nos:
            plan=plan_map.get(episode_no)
            if not plan:raise ValueError(f'第 {episode_no:02d} 集不在分集规划中')
            if plan['status']!='approved':raise ValueError(f'第 {episode_no:02d} 集规划尚未批准')
            validate_source_references(c,production_id,plan['sourceChapterRefs'])
            project_row=ensure_episode_for_plan(c,production_id,episode_no)
            script=c.execute('SELECT * FROM episode_scripts WHERE project_id=%s',(project_row['id'],)).fetchone()
            placeholders=','.join('%s' for _ in plan['sourceChapterRefs'])
            chapters=[]
            if plan['sourceChapterRefs']:
                chapters=[dict(row) for row in c.execute(f'''SELECT id,title,content,revision FROM source_chapters
                    WHERE id IN ({placeholders})''',plan['sourceChapterRefs']).fetchall()]
            prompt='''请生成且只生成目标单集剧本。\n已批准分集规划：'''+s.dumps(plan)+\
                '\n原著章节：'+s.dumps(chapters)+'\n本集现有剧本（为空则首次生成）：'+s.dumps(script_to_api(script))
            job_body=JobCreate(node_id='episode-script:'+project_row['id'],kind='text',
                submission_id=body.submission_id+f':{episode_no:03d}',input={
                    'provider':body.provider,'model':body.model,
                    'stage':'script_generation','prompt':prompt,'max_tokens':12000,
                    'episode_script_generation':{
                        'productionId':production_id,'episodeNo':episode_no,
                        'scriptRevision':script['revision'],'adaptationFingerprint':fingerprint,
                    },
            })
            created.append(create_job_record(c,project_row['id'],job_body))
        for item in created:
            s.event(item['project_id'],{'type':'job','id':item['id']},connection=c)
    return {'jobs':created,'count':len(created)}

@app.post('/api/projects/{pid}/run')
async def run_workflow(pid:str,request:Request):
    from .workflows import execution_plan
    body=await request.json();p=project(pid)
    with s.db() as c:
        project_state=read_project_state(c,pid)
    group=body.get('submission_id')
    if not isinstance(group,str) or len(group)<8 or len(group)>80: raise ValueError('批次提交标识无效')
    exact=body.get('exact') is True
    plan=execution_plan(
        p['document'],body.get('node_ids'),body.get('include_descendants') is True,exact,
    )
    providers={x['id']:x for x in s.get_setting('providers',[])}
    # Validate the entire batch before submitting its first runnable node.
    for node,_ in plan:
        data=node.get('data',{})
        if data.get('kind') not in ('text','storyboard','image','video'): continue
        provider_id=str(data.get('provider') or '').strip()
        provider=providers.get(provider_id)
        if not provider_id or provider_id=='local' or not provider:
            raise ValueError('部分节点未配置外部模型服务；系统不会自动回退或切换到其他服务')
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
        provider=providers.get(data.get('provider'))
        if provider and provider.get('type')=='volcengine_ark':
            if kind=='video':
                data=bind_fixed_dialogue_audio(
                    project_state['episode_document'],node['id'],kind,data,
                    available_audio_assets,
                    production_context=project_state['production_context'],
                )
            if kind=='video':
                data['parameters']={
                    'resolution':p['document'].get('videoResolution','720p'),
                    **(data.get('parameters') or {}),
                }
            from .providers.volcengine_ark import max_image_references
            reference_count=len(data['asset_ids'])+generated_image_parents
            if kind=='video' and reference_count>1:
                raise ValueError('当前火山方舟视频最多接受一张首帧，请只保留一条图像连线或一张素材')
            if kind=='video' and data.get('end_asset_id') and reference_count!=1:
                raise ValueError('使用火山方舟尾帧时必须同时保留一张首帧')
            if kind=='image' and reference_count>max_image_references(provider):
                raise ValueError(f'当前火山方舟图片模型最多支持 {max_image_references(provider)} 张参考图，请移除多余引用')
        if provider and provider.get('type')=='hc_atom':
            reference_count=len(data['asset_ids'])+generated_image_parents
            if kind=='video' and reference_count>1:
                raise ValueError('幻场 AI 通用视频接口最多提交一张参考图')
            if kind=='video' and data.get('end_asset_id'):
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
                )
                data['parameters']={
                    'resolution':p['document'].get('videoResolution','720p'),
                    **(data.get('parameters') or {}),
                }
        if provider and provider.get('type')=='minimax':
            # Hailuo accepts exactly one initial image.  Detect multiple
            # upstream image branches before any expensive parent job starts.
            if len(data['asset_ids'])+generated_image_parents>1:
                raise ValueError('MiniMax 图生视频仅接受一张首帧；请保留一条图像连线或在节点中选择一张素材')
        if not data.get('prompt','').strip():
            if not parents: raise ValueError(f'节点 {data.get("label",node["id"])} 缺少输入')
            data['prompt']={'text':'根据上游信息编写剧本','storyboard':'将上游剧本拆解为结构化分镜','image':'生成上游描述的电影画面','video':'根据上游画面与描述生成动态镜头'}[kind]
        data['project_style']=p['document'].get('style','')
        data['ratio']=(p['document'].get('videoRatio') or p['document'].get('ratio','16:9')) if kind=='video' else p['document'].get('ratio','16:9')
        if kind in ('text','storyboard'):
            data['target_duration']=data.get('target_duration') or p['document'].get('duration',15)
        if kind=='storyboard':
            data['film_bible']=data.get('film_bible') is not False
        prepared.append((node,parents,data,reference_sources))
    jobs_by_node={};created=[]
    with s.db() as c:
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
            result=create_job_record(c,pid,JobCreate(node_id=node['id'],kind=kind,submission_id=f'{group}:{node["id"]}',input=data))
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
        s.job_update(jid,status='cancelled',phase='已请求取消，等待运行引擎释放')
        # Re-read after cancellation so a provider handle attached between the
        # initial read and this state change is visible to remote cancellation.
        job=read_job(jid)
        with s.db() as c:
            snapshot=c.execute('SELECT provider FROM job_private WHERE job_id=%s',(jid,)).fetchone()
        if snapshot:
            provider=json.loads(snapshot['provider'])
            if provider.get('type')=='replicate':
                from .replicate_api import cancel as cancel_replicate
                cancel_replicate(job,provider)
            elif provider.get('type')=='volcengine_ark':
                from .providers.volcengine_ark import cancel as cancel_ark
                remote_cancelled=cancel_ark(job,provider)
                if remote_cancelled is True:
                    s.cancelled_phase(jid,'已取消本地等待，并已请求供应商取消远端任务')
                elif remote_cancelled is False:
                    s.cancelled_phase(jid,'本地已取消；供应商可能继续生成并产生费用')
            elif provider.get('type')=='hc_atom':
                from .providers.hc_atom import cancel as cancel_hc
                remote_cancelled=cancel_hc(job,provider)
                if remote_cancelled is True:
                    s.cancelled_phase(jid,'已取消本地等待，并已请求幻场 AI 取消远端任务')
                elif remote_cancelled is False:
                    s.cancelled_phase(jid,'本地已取消；幻场 AI 远端任务可能继续生成并产生费用')
            elif provider.get('type')=='runninghub':
                s.cancelled_phase(jid,'本地已取消；RunningHub 远端任务可能继续生成并产生费用')
    return read_job(jid)

@app.post('/api/jobs/{jid}/resume')
def resume(jid:str):
    # Remote jobs keep polling the original handle. Synchronous jobs do not have
    # one, so an explicit resume action requeues their frozen input instead.
    with s.db() as c:
        job=c.execute('SELECT * FROM jobs WHERE id=%s FOR UPDATE',(jid,)).fetchone()
        if not job: raise HTTPException(404,'任务不存在')
        if job['status'] in ('queued','running','succeeded'): return s.unpack(job)
        if job['status']!='interrupted': raise HTTPException(409,'只有中断任务可以恢复查询')
        snapshot=c.execute('SELECT provider FROM job_private WHERE job_id=%s',(jid,)).fetchone()
        provider=json.loads(snapshot['provider']) if snapshot else {}
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
    async def stream():
        requested = _requested_event_id(after, request.headers.get('last-event-id'))
        with s.db() as c:
            if requested is None:
                latest = c.execute('SELECT COALESCE(MAX(id),0) latest FROM events').fetchone()['latest']
                cursor = latest
            else:
                snapshot = c.execute('''SELECT
                    COALESCE((SELECT MAX(id) FROM events),0) latest,
                    (SELECT MIN(id) FROM events) oldest_retained,
                    EXISTS(SELECT 1 FROM events WHERE id=%s) requested_retained,
                    (SELECT COUNT(*) FROM (
                        SELECT id FROM events WHERE id>%s ORDER BY id LIMIT %s
                    ) visible) visible_backlog''',(
                    requested,requested,EVENT_BACKLOG_LIMIT+1,
                )).fetchone()
                cursor = _event_cursor(
                    snapshot['latest'],after,request.headers.get('last-event-id'),
                    oldest_retained=snapshot['oldest_retained'],
                    requested_retained=snapshot['requested_retained'],
                    visible_backlog=snapshot['visible_backlog'],
                )
        while not await request.is_disconnected():
            with s.db() as c:
                rows=c.execute('SELECT * FROM events WHERE id>%s ORDER BY id LIMIT 100',(cursor,)).fetchall()
            for row in rows:
                cursor=row['id']
                yield f'id: {cursor}\ndata: {s.dumps({"project_id":row["project_id"],**json.loads(row["payload"])})}\n\n'
            if not rows: yield ': heartbeat\n\n'
            await asyncio.sleep(2)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no'})

if (s.ROOT/'dist').is_dir():
    app.mount('/',StaticFiles(directory=s.ROOT/'dist',html=True),name='web')
