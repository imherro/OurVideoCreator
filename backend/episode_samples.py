"""Episode editor sample uploads: original retained, every version immutable."""
import asyncio
import mimetypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from uuid import UUID
from functools import lru_cache

from fastapi import APIRouter,File,Form,HTTPException,UploadFile
from fastapi.responses import FileResponse

from . import business_roles as br,collaboration as collab,identity,store as s
from .episode_deliveries import checksum
from .sample_media import normalize

router=APIRouter(prefix='/api/projects/{pid}/samples')


@lru_cache(maxsize=64)
def verified_hash(path,size,mtime_ns,ctime_ns):
    # Range seeks reuse a verification only while the immutable file stat agrees.
    return checksum(Path(path))


def scope(c,pid,write=False):
    project=collab.project_scope(c,pid)
    config=br.workflow(c,project['production_id'])
    if not config:raise HTTPException(409,'请先启用五角色生产流程')
    if write:
        br.require_role(c,project['production_id'],'editor')
        if br.default_assignee(c,project['production_id'],'editor',project_id=pid)!=identity.current().user_id:
            raise HTTPException(403,'请由本集剪辑负责人上传样片')
    return project,config


def public(row):
    value={key:row[key] for key in ('id','project_id','version','delivery_id','original_name','created_by','created')}
    value['metadata']=identity.json_value(row['metadata'])
    return value


def latest(c,pid):
    row=c.execute('SELECT id FROM episode_samples WHERE project_id=%s ORDER BY version DESC LIMIT 1',(pid,)).fetchone()
    return row['id'] if row else ''


@router.get('')
def listing(pid:str):
    with s.db() as c:
        project,config=scope(c,pid)
        return {'items':[public(row) for row in c.execute('SELECT * FROM episode_samples WHERE project_id=%s ORDER BY version DESC',(pid,))],
            'staffing_revision':config['revision'],'latest_id':latest(c,pid),
            'can_upload':'editor' in br.roles(c,project['production_id'],identity.current().user_id)
                and br.default_assignee(c,project['production_id'],'editor',project_id=pid)==identity.current().user_id}


def check_upload(c,pid,delivery_id,previous_id,staffing_revision):
    project,config=scope(c,pid,True)
    if config['revision']!=staffing_revision:raise HTTPException(409,'作品分工已变化，请刷新样片页面')
    if not c.execute('SELECT 1 FROM episode_deliveries WHERE id=%s AND project_id=%s',(delivery_id,pid)).fetchone():
        raise HTTPException(422,'请选择本集实际使用的交付包版本')
    if latest(c,pid)!=previous_id:raise HTTPException(409,'已有更新的样片版本，请刷新后核对再上传')
    return project


@router.post('',status_code=201)
async def upload(pid:str,file:UploadFile=File(...),delivery_id:str=Form(...),upload_id:str=Form(...),
                 previous_id:str=Form(''),staffing_revision:int=Form(...)):
    try:UUID(upload_id)
    except ValueError:raise HTTPException(422,'上传请求编号无效')
    name=Path(file.filename or 'sample').name;suffix=Path(name).suffix.lower()
    if suffix not in {'.mp4','.mov','.webm'}:raise HTTPException(422,'样片支持 MP4、MOV、WebM')
    with s.db() as c:
        collab.lock_identity(c);scope(c,pid,True)
        existing=c.execute('SELECT * FROM episode_samples WHERE project_id=%s AND upload_id=%s',(pid,upload_id)).fetchone()
        if not existing:check_upload(c,pid,delivery_id,previous_id,staffing_revision)
    folder=s.DATA/'samples';folder.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='sample-stage-',dir=folder) as stage:
        original=Path(stage)/('original'+suffix);review=Path(stage)/'review.mp4';total=0
        with original.open('wb') as output:
            while chunk:=await file.read(1024*1024):
                total+=len(chunk)
                if total>2*1024**3:raise HTTPException(413,'样片原文件不能超过 2 GB')
                output.write(chunk)
        original_hash=await asyncio.to_thread(checksum,original)
        if existing:
            with s.db() as c:scope(c,pid,True)
            if existing['original_sha256']!=original_hash or existing['delivery_id']!=delivery_id:
                raise HTTPException(409,'同一上传编号不能用于不同样片')
            return public(existing)
        try:metadata=await asyncio.to_thread(normalize,original,review)
        except subprocess.TimeoutExpired as error:raise HTTPException(422,'样片探测或转换超时；未发布新版本') from error
        review_hash=await asyncio.to_thread(checksum,review)
        metadata['original_bytes']=total;metadata['review_bytes']=review.stat().st_size
        with s.db() as c:
            identity.lock_identity_invariants(c)
            project=check_upload(c,pid,delivery_id,previous_id,staffing_revision)
            version=c.execute('SELECT COALESCE(MAX(version),0)+1 n FROM episode_samples WHERE project_id=%s',(pid,)).fetchone()['n']
            sid=s.uid('sample-');original_name=sid+suffix;review_name=sid+'-review.mp4'
            shutil.move(str(original),str(folder/original_name));shutil.move(str(review),str(folder/review_name))
            c.execute('''INSERT INTO episode_samples VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (sid,pid,version,delivery_id,upload_id,name,original_name,review_name,original_hash,review_hash,
                 s.dumps(metadata),identity.current().user_id,time.time()))
            identity.audit(c,'sample.upload','sample',sid,production_id=project['production_id'],workspace_id=project['workspace_id'],
                payload={'version':version,'delivery_id':delivery_id})
            s.event(pid,{'type':'sample_created','id':sid,'version':version},connection=c)
            return public(c.execute('SELECT * FROM episode_samples WHERE id=%s',(sid,)).fetchone())


@router.get('/{sid}/{variant}')
def media(pid:str,sid:str,variant:str):
    if variant not in {'review','original'}:raise HTTPException(404,'样片文件类型不存在')
    with s.db() as c:
        scope(c,pid)
        row=c.execute('SELECT * FROM episode_samples WHERE id=%s AND project_id=%s',(sid,pid)).fetchone()
        if not row:raise HTTPException(404,'样片版本不存在')
    folder=(s.DATA/'samples').resolve();path=(folder/row[variant+'_path']).resolve()
    if path.parent!=folder or not path.is_file():raise HTTPException(409,'样片文件丢失，不会自动替换旧版本')
    # Verification applies equally to range playback and original downloads.
    stat=path.stat()
    if verified_hash(str(path),stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)!=row[variant+'_sha256']:
        raise HTTPException(409,'样片完整性检查失败')
    original=variant=='original'
    return FileResponse(path,media_type=(mimetypes.guess_type(row['original_name'])[0] if original else 'video/mp4') or 'application/octet-stream',
        filename=row['original_name'] if original else f'sample-v{row["version"]}-review.mp4',
        content_disposition_type='attachment' if original else 'inline')
