"""Small ownership commands for existing scripts and chapters, not new content stores."""
import time
from typing import Literal

from fastapi import APIRouter, HTTPException

from . import owned_content as owned, identity, store as s
from .collaboration_routes import Assign, Comment, Version
from pydantic import Field

router=APIRouter(prefix='/api/productions/{production_id}/owned-content/{kind}/{target_id}')
Kind=Literal['chapter','script']


@router.get('')
def detail(production_id:str,kind:Kind,target_id:str):
    with s.db() as c:return owned.public(owned.load(c,production_id,kind,target_id))


class Restore(Version):
    revision:int=Field(ge=1)


@router.post('/restore')
def restore(production_id:str,kind:Kind,target_id:str,body:Restore):
    with s.db() as c:
        row=owned.load(c,production_id,kind,target_id,write=True)
        owned.authorize(c,row,body.expected_revision,body.assignment_epoch)
        table,key=('episode_script_revisions','project_id') if kind=='script' else ('source_chapter_revisions','chapter_id')
        old=c.execute(f'SELECT snapshot FROM {table} WHERE {key}=%s AND revision=%s',(target_id,body.revision)).fetchone()
        if not old:raise HTTPException(404,'历史版本不存在')
        snapshot=identity.json_value(old['snapshot'])
        if kind=='script':
            from .adaptation import save_script_row,validate_source_references,SCRIPT_FIELDS
            payload={key:snapshot[key] for key in SCRIPT_FIELDS}
            validate_source_references(c,production_id,payload['sourceChapterRefs'])
            save_script_row(c,row,payload,actor_id=identity.current().user_id)
        else:
            owned.history_before(c,row,'restore')
            c.execute('''UPDATE source_chapters SET title=%s,content=%s,revision=revision+1,
                status='in_progress',updated=%s,updated_by=%s WHERE id=%s''',
                (snapshot['title'],snapshot['content'],time.time(),identity.current().user_id,target_id))
            from .adaptation import mark_adaptation_stale
            mark_adaptation_stale(c,production_id,chapter_ids=[target_id])
        latest=owned.load(c,production_id,kind,target_id)
        owned.notify(c,latest,'restore')
        return owned.public(latest)


@router.post('/assign')
def assign(production_id:str,kind:Kind,target_id:str,body:Assign):
    with s.db() as c:
        return owned.assign(c,production_id,kind,target_id,body.expected_revision,body.assignment_epoch,body.assignee_id)


@router.get('/history')
def history(production_id:str,kind:Kind,target_id:str):
    with s.db() as c:
        row=owned.load(c,production_id,kind,target_id)
        table,key=('episode_script_revisions','project_id') if kind=='script' else ('source_chapter_revisions','chapter_id')
        values=c.execute(f'SELECT revision,snapshot,created FROM {table} WHERE {key}=%s ORDER BY revision DESC',(target_id,)).fetchall()
        return [{'revision':row['revision'],'snapshot':owned.snapshot(row),'created':row['updated']},
                *[{**dict(value),'snapshot':identity.json_value(value['snapshot'])} for value in values]]


@router.get('/comments')
def comments(production_id:str,kind:Kind,target_id:str):
    with s.db() as c:
        owned.load(c,production_id,kind,target_id)
        key='project_id' if kind=='script' else 'chapter_id'
        return [dict(row) for row in c.execute(f'''SELECT id,actor_user_id,body,created
            FROM source_script_comments WHERE {key}=%s ORDER BY created,id''',(target_id,))]


@router.post('/comments',status_code=201)
def comment(production_id:str,kind:Kind,target_id:str,body:Comment):
    if not body.body.strip():raise HTTPException(422,'评论不能为空')
    with s.db() as c:
        row=owned.load(c,production_id,kind,target_id,write=True)
        key='project_id' if kind=='script' else 'chapter_id'
        result=c.execute(f'''INSERT INTO source_script_comments(id,{key},actor_user_id,body,created)
            VALUES(%s,%s,%s,%s,%s) RETURNING id,actor_user_id,body,created''',
            (s.uid('comment-'),target_id,identity.current().user_id,body.body.strip(),time.time())).fetchone()
        owned.notify(c,row,'comment')
        return dict(result)


class ChapterReview(Version):
    action:Literal['submit','approve','return']


@router.post('/review')
def review(production_id:str,kind:Kind,target_id:str,body:ChapterReview):
    # Scripts retain the existing adaptation-readiness checks on their old small endpoints.
    if kind!='chapter':raise HTTPException(422,'请使用正式剧本审核接口')
    with s.db() as c:
        row=owned.load(c,production_id,kind,target_id,write=True)
        owned.authorize(c,row,body.expected_revision,body.assignment_epoch,reviewer=body.action!='submit')
        if body.action=='approve' and row['status']!='pending_review':raise HTTPException(409,'请先提交审核')
        if body.action=='submit' and not row['content'].strip():raise HTTPException(422,'章节正文不能为空')
        owned.history_before(c,row,'review')
        status={'submit':'pending_review','approve':'completed','return':'returned'}[body.action]
        c.execute('UPDATE source_chapters SET status=%s,revision=revision+1,updated_by=%s,updated=%s WHERE id=%s',
                  (status,identity.current().user_id,time.time(),target_id))
        latest=owned.load(c,production_id,kind,target_id)
        owned.notify(c,latest,'review')
        return owned.public(latest)
