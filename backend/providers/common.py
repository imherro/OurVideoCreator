"""Provider-neutral access to assets, HTTP errors and result registration."""
import mimetypes
import re
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .. import store as s
from .. import provider_egress
from ..provider_redaction import scrub
from ..media import probe


_GENERIC_RESULT_NAMES = {'生成结果', 'Seedream 生成图', '幻场 AI 生成图'}


def _clean_asset_label(value):
    label = re.sub(r'\bshot[-_ ]?(\d+)\b', lambda match: f'镜头 {int(match.group(1)):02d}',
                   str(value or '').strip(), flags=re.IGNORECASE)
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', label).strip(' .-')


def _registered_asset_name(job, requested_name, ext, existing_versions=0):
    """Display names only: stored media paths always retain their asset ID."""
    requested = Path(requested_name or '').name
    stem = Path(requested).stem
    suffix = Path(requested).suffix or ext
    inp = job.get('input') or {}
    explicit = _clean_asset_label(inp.get('output_name') or inp.get('asset_name'))
    if explicit:
        explicit_path = Path(explicit)
        base = explicit_path.stem if explicit_path.suffix else explicit
        return base.rstrip(' .-') + suffix
    label = _clean_asset_label(inp.get('asset_label') or inp.get('label'))
    if not label or not (stem in _GENERIC_RESULT_NAMES or stem.startswith('生成结果 ·')):
        return requested or ('生成素材' + suffix)
    qualifier = stem.removeprefix('生成结果').strip(' ·') if stem.startswith('生成结果 ·') else ''
    return ' · '.join(part for part in (label, qualifier, f'V{existing_versions + 1}') if part) + suffix


class RecoverableProviderError(Exception):
    """A temporary error after a durable upstream handle has been obtained."""


def checked(response, recoverable=False):
    if not response.is_success:
        try:
            body=response.json()
            error=body.get('error') or body.get('detail') or body
            if isinstance(error,dict): error=error.get('message') or str(error)
        except Exception: error=response.text[:400]
        guidance={401:'鉴权失败，请检查该服务的 API Key。',403:'服务拒绝访问，请检查账号权限和模型授权。',402:'服务额度不足，请核对供应商余额或配额后再提交。',429:'服务限流或配额受限，请查看供应商限制，稍后手动重试。',404:'接口或模型不存在，请检查服务地址和模型 ID。',413:'输入素材过大，请缩小文件后重试。',422:'输入参数不受支持，请检查模型能力、分辨率和参考素材。'}.get(response.status_code,'服务暂时异常，请核对供应商状态后重试。' if response.status_code>=500 else '请核对任务参数。')
        message=f'模型服务返回 {response.status_code}：{guidance} 详情：{scrub(str(error))[:500]}'
        if recoverable and (response.status_code==429 or response.status_code>=500):
            raise RecoverableProviderError(message)
        raise ValueError(message)
    return scrub(response.json())


def assets_for(job):
    with s.db() as c:
        assets=[]
        for aid in job['input'].get('asset_ids',[]):
            row=c.execute('''SELECT a.* FROM assets a
                JOIN projects origin ON origin.id=a.project_id
                JOIN projects target ON target.id=%s
                WHERE a.id=%s AND COALESCE(a.production_id,origin.production_id,origin.id)=COALESCE(target.production_id,target.id)
                AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='asset' AND d.item_id=a.id)
            ''',(job['project_id'],aid)).fetchone()
            if not row: raise ValueError('引用素材已丢失')
            assets.append(s.unpack(row))
    return assets


def assets_by_ids(job, asset_ids):
    """Resolve production-scoped assets in the caller's explicit order."""
    resolved = []
    with s.db() as c:
        for aid in asset_ids:
            row = c.execute('''SELECT a.* FROM assets a
                JOIN projects origin ON origin.id=a.project_id
                JOIN projects target ON target.id=%s
                WHERE a.id=%s AND COALESCE(a.production_id,origin.production_id,origin.id)=COALESCE(target.production_id,target.id)
                AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='asset' AND d.item_id=a.id)
            ''', (job['project_id'], aid)).fetchone()
            if not row:
                raise ValueError('引用素材已丢失')
            resolved.append(s.unpack(row))
    return resolved


def download_file(url, ext, recoverable=False):
    if urlparse(url).scheme not in ('http','https'):
        raise ValueError('模型结果不是有效媒体地址')
    path = s.DATA / (s.uid('download-') + ext)
    try:
        # Provider credentials are intentionally never forwarded to result hosts.
        with provider_egress.client(follow_redirects=True, timeout=120) as client, client.stream('GET',url) as response:
            if not response.is_success:
                response.read()
                checked(response, recoverable=recoverable)
            size = 0
            with path.open('wb') as out:
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 2*1024**3:
                        raise ValueError('输出超过 2GB，请降低分辨率或时长')
                    out.write(chunk)
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def register(job,path,name=None,category=None,asset_source='generated'):
    with s.db() as c:
        row=c.execute('SELECT status FROM jobs WHERE id=%s',(job['id'],)).fetchone()
    if not row or row['status']=='cancelled': raise InterruptedError()
    aid=s.uid('asset-')
    source=Path(path)
    ext=source.suffix.lower()
    target=s.asset_path(aid,ext)
    try:
        if source!=target: shutil.copyfile(source,target)
        mime=mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        kind='image' if mime.startswith('image/') else 'audio' if mime.startswith('audio/') else 'video'
        metadata={'job_id':job['id'],'node_id':job['node_id'],'input':job['input'],'bytes':target.stat().st_size}
        fingerprint=job.get('input',{}).get('generation_fingerprint')
        if fingerprint:metadata['generationFingerprint']=fingerprint
        if kind=='image':
            from PIL import Image
            with Image.open(target) as img: metadata.update(width=img.width,height=img.height)
        elif kind in ('audio','video'):
            metadata.update(probe(target))
        semantic=category or job.get('input',{}).get('asset_category') or ('shot' if kind in ('image','video') else 'other')
        if semantic not in {'character','scene','prop','shot','music','sfx','voice','reference','other'}:raise ValueError('生成素材分类无效')
        result={'id':aid,'url':f'/api/assets/{aid}/file','name':name or source.name,'kind':kind,'category':semantic,'source':asset_source}
        if fingerprint:result['generationFingerprint']=fingerprint
        with s.db() as c:
            # Separate jobs for the same node may register concurrently inside
            # the single Worker. Serialize only this display-version group.
            # Take this before the job row so cancellation can win while waiting.
            group=s.dumps(['asset-name',job['project_id'],job['node_id'],kind])
            c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(group,))
            state=c.execute('SELECT status FROM jobs WHERE id=%s FOR UPDATE',(job['id'],)).fetchone()
            if not state or state['status']=='cancelled':raise InterruptedError('结果登记前任务已取消')
            origin=c.execute('SELECT production_id FROM projects WHERE id=%s',(job['project_id'],)).fetchone()
            if not origin:raise ValueError('生成任务所属项目不存在')
            count=c.execute("SELECT count(*) n FROM assets WHERE project_id=%s AND kind=%s AND metadata->>'node_id'=%s",
                            (job['project_id'],kind,job['node_id'])).fetchone()['n']
            result['name']=_registered_asset_name(job,name or source.name,ext,count)
            c.execute('INSERT INTO assets(id,project_id,name,kind,path,mime,metadata,created,category,source,production_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(aid,job['project_id'],result['name'],kind,target.name,mime,s.dumps(metadata),time.time(),semantic,asset_source,origin['production_id']))
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return result


def download_result(job,url,ext,recoverable=False):
    path=download_file(url,ext,recoverable=recoverable)
    try:
        return register(job,path,'生成结果'+ext)
    finally: path.unlink(missing_ok=True)
