"""Fixed-version handoffs of explicitly selected media, not a new approval stage."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time
import zipfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field

from . import business_roles as br, collaboration as collab, identity, store as s
from .collaboration_routes import StrictBody

router=APIRouter(prefix='/api/projects/{pid}/deliveries')


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')


def scope(c,pid,*,write=False):
    project=collab.project_scope(c,pid)
    if not br.workflow(c,project['production_id']):raise HTTPException(409,'请先启用五角色流程')
    if write:
        br.require_role(c,project['production_id'],'generator')
        if br.default_assignee(c,project['production_id'],'generator',project_id=pid)!=identity.current().user_id:
            raise HTTPException(403,'只有本集抽卡师可以确认交付')
    return project


def snapshot(c,pid):
    """Called inside the short identity/content barrier, never during ZIP copying."""
    project=scope(c,pid)
    episode=c.execute('SELECT episode_no,episode_title,revision FROM projects WHERE id=%s',(pid,)).fetchone()
    script=c.execute('SELECT title,body,status,revision,assignment_epoch FROM episode_scripts WHERE project_id=%s',(pid,)).fetchone()
    rows=list(c.execute('SELECT * FROM collaboration_objects WHERE project_id=%s AND NOT deleted ORDER BY id',(pid,)))
    graph=next((identity.json_value(row['content']) for row in rows if row['kind']=='graph'),{})
    shots={}
    for row in rows:
        if row['kind']=='shot':
            content=identity.json_value(row['content']);shot=content['shot']
            shots[shot.get('uid') or shot['id']]=(row,content)
    order=graph.get('shotOrder') or []
    issues=[];files=[];items=[]
    if len(order)!=len(set(order)) or set(order)!=set(shots):issues.append('镜头顺序与本集镜头不一致，请先保存画布')
    if not shots:issues.append('本集还没有镜头')
    if not script or script['status']!='approved':issues.append('本集剧本尚未通过验收')
    prefix=f"E{episode['episode_no']:03d}"
    def media(aid,kind,label,filename):
        asset=c.execute('''SELECT * FROM assets WHERE id=%s AND production_id=%s
            AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='asset' AND d.item_id=assets.id)
            AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=assets.project_id)''',
            (aid,project['production_id'])).fetchone() if aid else None
        if not asset or asset['kind']!=kind:
            issues.append(label+'缺少已选定的'+('视频' if kind=='video' else '音频'));return None
        path=s.stored_asset_path(asset['path'])
        if not path.is_file():issues.append(label+'素材文件丢失');return None
        if path.stat().st_size==0:issues.append(label+'素材文件为空');return None
        extension=path.suffix.lower()
        if not extension or len(extension)>10 or not extension[1:].isalnum():extension='.bin'
        entry={'asset_id':aid,'kind':kind,'filename':filename+extension,'bytes':path.stat().st_size}
        files.append(entry)
        return entry['filename']
    for index,uid in enumerate(order,1):
        if uid not in shots:continue
        row,content=shots[uid];shot=content['shot'];label=f'第 {index} 镜'
        node_id=shot.get('videoNode') or (shot.get('pipeline') or {}).get('videoNodeId')
        node=next((node for node in content['nodes'] if node['id']==node_id),{})
        data=node.get('data') or {}
        if data.get('stale') or shot.get('prompts_need_review'):issues.append(label+'选定结果已过期，请重新核对并采纳')
        filename=media(data.get('assetId'),'video',label,f'video/{prefix}_S{index:04d}')
        dialogue=[]
        for line_index,line in enumerate(shot.get('dialogues') or [],1):
            audio=None
            if line.get('audioAssetId'):
                audio=media(line['audioAssetId'],'audio',label+'对白',f'audio/{prefix}_S{index:04d}_D{line_index:03d}')
            dialogue.append({'character':line.get('characterName') or line.get('characterCardId') or '',
                'text':line.get('text') or '', 'audio':audio})
        items.append({'number':index,'shot_id':shot['id'],'shot_uid':uid,'object_id':row['id'],
            'revision':row['revision'],'video':filename,'dialogues':dialogue})
    # Keep existing explicitly placed timeline audio, but never all generated candidates.
    audio_ids=set()
    def collect(value):
        if isinstance(value,dict):
            for key,child in value.items():
                if key in {'assetId','srcAssetId','audioId'} and isinstance(child,str):audio_ids.add(child)
                else:collect(child)
        elif isinstance(value,list):
            for child in value:collect(child)
    for row in rows:
        if row['kind']=='timeline':collect(identity.json_value(row['content']))
    existing={item['asset_id'] for item in files}
    for aid in sorted(audio_ids-existing):
        asset=c.execute('SELECT kind FROM assets WHERE id=%s AND production_id=%s',(aid,project['production_id'])).fetchone()
        if asset and asset['kind']=='audio':media(aid,'audio','粗剪时间线音频',f'audio/{prefix}_extra_{len(files):04d}')
    if sum(item['bytes'] for item in files)>8*1024**3:issues.append('交付素材超过 8 GB，请减少单集素材体积后重试')
    manifest={'format':'ourvideocreator-delivery/v1','episode_no':episode['episode_no'],
        'episode_title':episode['episode_title'],'script':dict(script) if script else None,'shots':items,'files':files}
    # Include the complete revision set and staffing fence in the confirmation.
    fence={'manifest':manifest,'objects':[(r['id'],r['revision'],r['assignment_epoch']) for r in rows],
        'workflow_revision':br.workflow(c,project['production_id'])['revision'],'episode_revision':episode['revision']}
    return {'fingerprint':hashlib.sha256(encoded(fence)).hexdigest(),'manifest':manifest,'issues':issues}


def public(row):
    value={key:row[key] for key in ('id','project_id','version','manifest','created_by','created')}
    value['manifest']=identity.json_value(value['manifest'])
    return value


@router.get('')
def deliveries(pid:str):
    with s.db() as c:
        scope(c,pid)
        return [public(row) for row in c.execute('SELECT * FROM episode_deliveries WHERE project_id=%s ORDER BY version DESC',(pid,))]


@router.get('/preview')
def preview(pid:str):
    with s.db() as c:
        identity.lock_identity_invariants(c)
        return snapshot(c,pid)


class Confirm(StrictBody):
    fingerprint:str=Field(pattern=r'^[a-f0-9]{64}$')


def checksum(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


@router.post('',status_code=201)
def create(pid:str,body:Confirm):
    with s.db() as c:
        identity.lock_identity_invariants(c);project=scope(c,pid,write=True)
        prepared=snapshot(c,pid)
        if prepared['fingerprint']!=body.fingerprint:raise HTTPException(409,'交付内容已变化，请刷新清单后重新确认')
        if prepared['issues']:raise HTTPException(409,{'message':'交付尚未就绪','issues':prepared['issues']})
        previous=c.execute('SELECT * FROM episode_deliveries WHERE project_id=%s AND fingerprint=%s',(pid,body.fingerprint)).fetchone()
        if previous:return public(previous)
        sources={entry['asset_id']:s.stored_asset_path(c.execute('SELECT path FROM assets WHERE id=%s',(entry['asset_id'],)).fetchone()['path'])
                 for entry in prepared['manifest']['files']}
    folder=s.DATA/'deliveries';folder.mkdir(exist_ok=True)
    # Only our disposable staging directory is removed by this context manager.
    with tempfile.TemporaryDirectory(prefix='delivery-stage-',dir=folder) as stage:
        archive=Path(stage)/'bundle.zip';manifest=prepared['manifest']
        try:
            with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as bundle:
                for entry in manifest['files']:
                    digest=hashlib.sha256();total=0
                    with sources[entry['asset_id']].open('rb') as source,bundle.open(entry['filename'],'w',force_zip64=True) as dest:
                        while chunk:=source.read(1024*1024):
                            if total+len(chunk)>entry['bytes']:raise HTTPException(409,'素材文件发生变化，请重新确认交付')
                            total+=len(chunk);digest.update(chunk);dest.write(chunk)
                    if total!=entry['bytes']:raise HTTPException(409,'素材文件发生变化，请重新确认交付')
                    entry['sha256']=digest.hexdigest()
                bundle.writestr('manifest.json',encoded(manifest))
                bundle.writestr('script.txt',(manifest['script']['title']+'\n\n'+manifest['script']['body']).encode('utf-8'))
                lines=[f"{shot['number']:04d}\t{shot['shot_id']}\t{shot['video']}" for shot in manifest['shots']]
                bundle.writestr('shots.tsv',('order\tshot_id\tfile\n'+'\n'.join(lines)).encode('utf-8-sig'))
                dialogue=['%04d\t%s\t%s'%(shot['number'],line['character'],line['text']) for shot in manifest['shots'] for line in shot['dialogues']]
                bundle.writestr('dialogue.txt','\n'.join(dialogue).encode('utf-8'))
        except FileNotFoundError as error:raise HTTPException(409,'素材文件丢失，请刷新交付清单') from error
        archive_hash=checksum(archive)
        with s.db() as c:
            identity.lock_identity_invariants(c);scope(c,pid,write=True)
            current=snapshot(c,pid)
            if current['fingerprint']!=body.fingerprint or current['issues']:
                raise HTTPException(409,'打包期间内容或分工已变化，未发布交付包，请重新确认')
            previous=c.execute('SELECT * FROM episode_deliveries WHERE project_id=%s AND fingerprint=%s',(pid,body.fingerprint)).fetchone()
            if previous:return public(previous)
            version=c.execute('SELECT COALESCE(MAX(version),0)+1 n FROM episode_deliveries WHERE project_id=%s',(pid,)).fetchone()['n']
            did=s.uid('delivery-');name=did+'.zip'
            shutil.move(str(archive),str(folder/name))
            c.execute('''INSERT INTO episode_deliveries VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (did,pid,version,body.fingerprint,s.dumps(manifest),name,archive_hash,identity.current().user_id,time.time()))
            identity.audit(c,'delivery.create','delivery',did,production_id=project['production_id'],workspace_id=project['workspace_id'],payload={'version':version})
            s.event(pid,{'type':'delivery_created','id':did,'version':version},connection=c)
            return public(c.execute('SELECT * FROM episode_deliveries WHERE id=%s',(did,)).fetchone())


@router.get('/{did}/download')
def download(pid:str,did:str):
    with s.db() as c:
        scope(c,pid)
        row=c.execute('SELECT * FROM episode_deliveries WHERE id=%s AND project_id=%s',(did,pid)).fetchone()
        if not row:raise HTTPException(404,'交付版本不存在')
    folder=(s.DATA/'deliveries').resolve();path=(folder/row['archive_name']).resolve()
    if path.parent!=folder or not path.is_file():raise HTTPException(409,'交付包文件丢失；原版本不会自动替换')
    if checksum(path)!=row['archive_sha256']:raise HTTPException(409,'交付包完整性检查失败；原版本不会自动替换')
    manifest=identity.json_value(row['manifest'])
    return FileResponse(path,media_type='application/zip',filename=f"E{manifest['episode_no']:03d}_delivery_v{row['version']}.zip")
