"""Small metadata commands; neither accepts an aggregate project document."""
import json
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import collaboration as collab, identity, model_validation, platform_models, store as s
from .generation_policy import validate_generation_policy

router = APIRouter()
EPISODE_FIELDS = {'brief', 'ratio', 'duration', 'videoResolution', 'videoRatio',
                  'videoDuration', 'videoFormat', 'characters'}
BIBLE_FIELDS = {'story', 'style', 'continuity', 'styleVersion'}


class Metadata(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=1)
    patch: dict


def check_episode(patch):
    if set(patch) - EPISODE_FIELDS - {'name'}:
        raise HTTPException(422, '元数据接口不接受协作对象或整份 document')
    for key in ('brief', 'name', 'ratio', 'videoResolution', 'videoRatio', 'videoFormat'):
        if key in patch and not isinstance(patch[key], str):
            raise HTTPException(422, '元数据文本字段无效')
    if 'name' in patch and len(patch['name']) > 100:
        raise HTTPException(422, '分集名称不能超过 100 字符')
    for key, values in {'ratio': {'21:9','16:9','4:3','1:1','3:4','9:16'},
                        'videoRatio': {'21:9','16:9','4:3','1:1','3:4','9:16','adaptive'},
                        'videoResolution': {'480p','720p','1080p'}, 'videoFormat': {'mp4','mov'}}.items():
        if key in patch and patch[key] not in values:
            raise HTTPException(422, '分集输出规格无效')
    for key in ('duration', 'videoDuration'):
        if key in patch:
            value = patch[key]
            if isinstance(value, bool) or not isinstance(value, (int,float)):
                raise HTTPException(422, '分集时长无效')
            if key == 'duration' and not 5 <= value <= 3000:
                raise HTTPException(422, '分集目标时长须为 5–3000 秒')
            if key == 'videoDuration' and not (value == -1 or 4 <= value <= 30):
                raise HTTPException(422, '视频输出时长须为 -1 或 4–30 秒')
    if 'characters' in patch and not isinstance(patch['characters'], list):
        raise HTTPException(422, '旧角色资料必须为列表')


@router.patch('/api/projects/{pid}/metadata')
def episode_metadata(pid: str, body: Metadata):
    model_validation.reject_private_overrides(body.patch)
    check_episode(body.patch)
    with s.db() as c:
        collab.lock_identity(c)
        scope = collab.project_scope(c, pid, 'manager')
        row = c.execute('SELECT * FROM projects WHERE id=%s FOR UPDATE', (pid,)).fetchone()
        identity.require_production(c, collab.live_principal(c), row['production_id'], 'manager')
        if row['revision'] != body.expected_revision:
            raise HTTPException(409, {'type': 'metadata', 'revision': row['revision']})
        collab.validate_asset_references(c,row['production_id'],body.patch)
        metadata = json.loads(row['document'])
        metadata.update({key: value for key,value in body.patch.items() if key in EPISODE_FIELDS})
        now = time.time()
        name = body.patch.get('name', row['name']).strip() or '未命名短片'
        c.execute('INSERT INTO revisions VALUES(%s,%s,%s,%s,%s)',
                  (s.uid(), pid, row['revision'], row['document'], now))
        c.execute('''UPDATE projects SET name=%s,episode_title=%s,document=%s,revision=revision+1,updated=%s
            WHERE id=%s AND revision=%s''', (name,name,s.dumps(metadata),now,pid,body.expected_revision))
        identity.audit(c,'episode.metadata','project',pid,workspace_id=scope['workspace_id'],production_id=row['production_id'])
        s.event(pid,{'type':'project','revision':row['revision']+1},connection=c)
    return {'revision':row['revision']+1,'name':name,'updated':now}


@router.patch('/api/productions/{production_id}/context')
def production_metadata(production_id: str, body: Metadata):
    model_validation.reject_private_overrides(body.patch)
    patch = dict(body.patch)
    if set(patch) - {'style','generationPolicy','filmBible'}:
        raise HTTPException(422, '作品设置只能修改风格、模型策略和故事设定')
    if 'filmBible' in patch and (not isinstance(patch['filmBible'], dict) or set(patch['filmBible']) - BIBLE_FIELDS):
        raise HTTPException(422, '视觉卡、版本和音色必须使用独立对象命令')
    bible=patch.get('filmBible',{})
    if any(key in bible and not isinstance(bible[key],dict) for key in ('story','style','continuity')):
        raise HTTPException(422,'故事、风格和连续性设定须为对象')
    if 'styleVersion' in bible and (isinstance(bible['styleVersion'],bool) or not isinstance(bible['styleVersion'],int) or bible['styleVersion']<1):
        raise HTTPException(422,'风格版本必须为正整数')
    if 'style' in patch and (not isinstance(patch['style'],str) or not patch['style'].strip()):
        raise HTTPException(422, '视觉风格不能为空')
    if 'generationPolicy' in patch:
        patch['generationPolicy'] = validate_generation_policy(patch['generationPolicy'],platform_models.compiler_catalog(),allow_missing=True)
    with s.db() as c:
        collab.lock_identity(c)
        identity.require_production(c,collab.live_principal(c),production_id,'manager')
        row = c.execute('SELECT * FROM productions WHERE id=%s FOR UPDATE',(production_id,)).fetchone()
        identity.require_production(c,collab.live_principal(c),production_id,'manager')
        if row['revision'] != body.expected_revision:
            raise HTTPException(409,{'type':'production_metadata','revision':row['revision']})
        collab.validate_asset_references(c,production_id,body.patch)
        context = json.loads(row['shared_context'])
        bible = patch.pop('filmBible', None)
        old_bible=context.get('filmBible') or {}
        previous_style_version=old_bible.get('styleVersion',1)
        if bible is not None and bible.get('styleVersion',previous_style_version)<previous_style_version:
            raise HTTPException(422,'风格版本不能倒退')
        style_changed=('style' in patch and patch['style']!=context.get('style')) or (
            bible is not None and 'style' in bible and bible['style']!=old_bible.get('style',{}))
        context.update(patch)
        if bible is not None:
            context.setdefault('filmBible',{}).update(bible)
        if style_changed:
            context.setdefault('filmBible',{})['styleVersion']=max(previous_style_version+1,
                context['filmBible'].get('styleVersion',1))
        now=time.time()
        c.execute('INSERT INTO production_revisions(id,production_id,revision,shared_context,created) VALUES(%s,%s,%s,%s,%s)',
                  (s.uid(),production_id,row['revision'],row['shared_context'],now))
        c.execute('UPDATE productions SET shared_context=%s,revision=revision+1,updated=%s WHERE id=%s AND revision=%s',
                  (s.dumps(context),now,production_id,body.expected_revision))
        identity.audit(c,'production.metadata','production',production_id,workspace_id=row['workspace_id'],production_id=production_id)
        for episode in c.execute('SELECT id FROM projects WHERE production_id=%s ORDER BY id',(production_id,)):
            s.event(episode['id'],{'type':'production','revision':row['revision']+1},connection=c)
    return {'revision':row['revision']+1,'updated':now}
