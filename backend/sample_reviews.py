"""Small episode review log; no task platform or new permission system."""
import time
from typing import Literal

from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field

from . import business_roles as br,identity,store as s
from .episode_samples import scope,latest,verified_media

router=APIRouter(prefix='/api/projects/{pid}/samples')


class ReviewEvent(BaseModel):
    kind:Literal['comment','reply','resolve','reopen','approve','return']
    revision:int=Field(ge=0)
    staffing_revision:int=Field(ge=0)
    latest_id:str
    frame:int|None=Field(default=None,ge=0)
    parent_id:str|None=None
    related_sample_id:str|None=None
    body:str=Field(default='',max_length=4000)


def events(c,pid):
    return [dict(row) for row in c.execute('''SELECT e.*,u.nickname author FROM sample_review_events e
        JOIN users u ON u.id=e.created_by WHERE e.project_id=%s ORDER BY e.revision''',(pid,))]


def unresolved(items):
    opened={}
    for item in items:
        if item['kind']=='comment':opened[item['id']]=item
        elif item['kind']=='resolve':opened.pop(item['parent_id'],None)
        elif item['kind']=='reopen':
            parent=next(row for row in items if row['id']==item['parent_id'])
            opened[parent['id']]=parent
    return list(opened.values())


def sample(c,pid,sid):
    row=c.execute('SELECT * FROM episode_samples WHERE id=%s AND project_id=%s',(sid,pid)).fetchone()
    if not row:raise HTTPException(404,'样片版本不存在')
    return row


def state(c,pid,sid):
    project,config=scope(c,pid);sample(c,pid,sid)
    items=events(c,pid);head=latest(c,pid);open_items=unresolved(items)
    decisions=[row for row in items if row['sample_id']==sid and row['kind'] in ('approve','return')]
    decision=decisions[-1] if decisions else None
    # A new concern after approval cannot leave a green approval badge in place.
    status=decision['kind'] if decision else 'pending'
    if status=='approve' and any(item['revision']>decision['revision'] and item['kind'] in ('comment','reopen')
            and (sid==head or item['sample_id']==sid) for item in items):status='pending'
    user=identity.current().user_id;roles=br.roles(c,project['production_id'],user)
    return {'events':items,'revision':items[-1]['revision'] if items else 0,
        'latest_id':head,'staffing_revision':config['revision'],'status':status,
        'unresolved_ids':[row['id'] for row in open_items],
        'can_review':'producer' in roles,
        'can_reply':'editor' in roles and br.default_assignee(c,project['production_id'],'editor',project_id=pid)==user}


@router.get('/{sid}/review-events')
def listing(pid:str,sid:str):
    with s.db() as c:return state(c,pid,sid)


@router.post('/{sid}/review-events',status_code=201)
def append(pid:str,sid:str,body:ReviewEvent):
    verified=[]
    if body.kind=='approve':
        with s.db() as c:
            project,_=scope(c,pid)
            br.require_role(c,project['production_id'],'producer')
            candidate=sample(c,pid,sid)
        # Hash large originals outside the global identity transaction. Media
        # versions are immutable; check the same file stats again before commit.
        for variant in ('original','review'):
            path=verified_media(candidate,variant);stat=path.stat()
            verified.append((path,(stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)))
    with s.db() as c:
        identity.lock_identity_invariants(c)
        project,config=scope(c,pid);row=sample(c,pid,sid)
        if body.kind=='reply':scope(c,pid,True)
        else:br.require_role(c,project['production_id'],'producer')
        current=state(c,pid,sid)
        if body.revision!=current['revision'] or body.latest_id!=current['latest_id'] or body.staffing_revision!=config['revision']:
            raise HTTPException(409,'样片、批注或分工已变化，请刷新并重新确认')
        text=body.body.strip()
        if body.kind in ('comment','reply','return') and not text:raise HTTPException(422,'请填写批注、回复或退回原因')
        if body.kind=='comment':
            count=identity.json_value(row['metadata'])['frame_count']
            if body.frame is None or body.frame>=count:raise HTTPException(422,'批注帧不在本样片范围内')
        elif body.frame is not None:raise HTTPException(422,'只有批注可指定帧')
        if body.kind in ('reply','resolve','reopen'):
            parent=next((item for item in current['events'] if item['id']==body.parent_id),None)
            if not parent or parent['kind']!='comment' or parent['sample_id']!=sid:
                raise HTTPException(422,'请选择本样片版本中的原批注')
            is_open=parent['id'] in current['unresolved_ids']
            if body.kind=='resolve' and not is_open:raise HTTPException(409,'此批注已经确认解决')
            if body.kind=='reopen' and is_open:raise HTTPException(409,'此批注仍待解决')
        elif body.parent_id:raise HTTPException(422,'该操作不接受原批注编号')
        if body.related_sample_id:
            if body.kind!='reply':raise HTTPException(422,'仅回复可以关联修改后的样片')
            related=sample(c,pid,body.related_sample_id)
            if related['version']<row['version']:raise HTTPException(422,'修改结果不能关联更早样片')
        if body.kind in ('approve','return'):
            if sid!=current['latest_id']:raise HTTPException(409,'请审查最新样片；旧版审批历史保留')
            if body.kind=='approve' and current['unresolved_ids']:
                raise HTTPException(409,'还有未确认解决的批注，请核对修改结果后再批准')
        for path,expected in verified:
            try:stat=path.stat()
            except OSError as error:raise HTTPException(409,'样片文件已不可用，请重新核对') from error
            if (stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)!=expected:
                raise HTTPException(409,'样片文件在审核期间发生变化，请重新核对')
        eid=s.uid('review-')
        c.execute('''INSERT INTO sample_review_events
            (id,project_id,sample_id,revision,kind,frame,parent_id,related_sample_id,body,created_by,created)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (eid,pid,sid,current['revision']+1,body.kind,body.frame,body.parent_id,body.related_sample_id,
             text,identity.current().user_id,time.time()))
        identity.audit(c,'sample.'+body.kind,'sample',sid,production_id=project['production_id'],workspace_id=project['workspace_id'],
            payload={'review_event':eid,'review_sha256':row['review_sha256'],'revision':current['revision']+1})
        s.event(pid,{'type':'sample_review_changed','sample_id':sid},connection=c)
        return state(c,pid,sid)
