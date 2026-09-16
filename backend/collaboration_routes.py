"""Scoped HTTP commands for P5 collaboration objects."""
import json
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import collaboration as collab, store as s

router = APIRouter(prefix='/api/projects/{pid}/objects')


class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Create(StrictBody):
    kind: Literal['shot', 'node', 'visual_card', 'graph', 'timeline', 'director']
    content: dict


class Version(StrictBody):
    expected_revision: int = Field(ge=1)
    assignment_epoch: int = Field(ge=1)


class Save(Version):
    content: dict
    lease_token: str | None = None
    lease_epoch: int | None = None


class Assign(Version):
    assignee_id: str | None


class Lease(StrictBody):
    action: Literal['acquire', 'renew', 'release']
    assignment_epoch: int = Field(ge=1)
    token: str | None = None
    lease_epoch: int | None = None


class Review(Version):
    action: Literal['submit', 'approve', 'return']


class Restore(Version):
    revision: int = Field(ge=1)
    lease_token: str | None = None
    lease_epoch: int | None = None


class Comment(StrictBody):
    body: str = Field(min_length=1, max_length=8000)


class BatchItem(Save):
    id: str


class Batch(StrictBody):
    operations: list[BatchItem] = Field(min_length=1, max_length=200)


class Delete(Version):
    id: str


class Commands(StrictBody):
    creates: list[Create] = Field(default_factory=list, max_length=200)
    updates: list[BatchItem] = Field(default_factory=list, max_length=200)
    deletes: list[Delete] = Field(default_factory=list, max_length=200)


@router.get('')
def objects(pid: str):
    with s.db() as c:
        scope = collab.project_scope(c, pid)
        return [collab.public(row) for row in c.execute('''SELECT * FROM collaboration_objects
            WHERE production_id=%s AND (project_id=%s OR project_id IS NULL) AND NOT deleted
            ORDER BY kind,id''', (scope['production_id'], pid))]


@router.post('', status_code=201)
def create_object(pid: str, body: Create):
    with s.db() as c:
        if body.kind in {'shot','node'}:
            collab.validate_content(body.kind,body.content)
            scope=collab.project_scope(c,pid,'editor')
            graph=c.execute("SELECT * FROM collaboration_objects WHERE project_id=%s AND kind='graph' AND NOT deleted",(pid,)).fetchone()
            if not graph:
                raise HTTPException(409,'当前分集缺少协作结构；旧测试数据不自动迁移')
            content=json.loads(graph['content'])
            for nid in collab.validation.node_ids(body.kind,body.content):
                content['nodeOrder'].append(nid)
                content['positions'][nid]={'x':0,'y':0}
            if body.kind=='shot':
                content['shotOrder'].append(collab.validation.envelope(body.kind,body.content))
            result=collab.commands(c,pid,creates=[body.model_dump()],updates=[{
                'id':graph['id'],'expected_revision':graph['revision'],'assignment_epoch':graph['assignment_epoch'],
                'content':content}],deletes=[])
            return result['created'][0]
        return collab.create(c, pid, body.kind, body.content)


@router.get('/{oid}')
def object_detail(pid: str, oid: str):
    with s.db() as c:
        return collab.public(collab.load(c, pid, oid))


@router.post('/batch')
def save_batch(pid: str, body: Batch):
    with s.db() as c:
        return collab.commands(c,pid,creates=[],updates=[item.model_dump() for item in body.operations],deletes=[])['updated']


@router.post('/commands')
def object_commands(pid: str, body: Commands):
    with s.db() as c:
        return collab.commands(c,pid,**body.model_dump())


@router.patch('/{oid}')
def save_object(pid: str, oid: str, body: Save):
    with s.db() as c:
        return collab.commands(c,pid,creates=[],updates=[{'id':oid,**body.model_dump()}],deletes=[])['updated'][0]


@router.post('/{oid}/assign')
def assign_object(pid: str, oid: str, body: Assign):
    with s.db() as c:
        return collab.assign(c, pid, oid, **body.model_dump())


@router.post('/{oid}/lease')
def object_lease(pid: str, oid: str, body: Lease):
    with s.db() as c:
        return collab.lease(c, pid, oid, **body.model_dump())


@router.post('/{oid}/review')
def review_object(pid: str, oid: str, body: Review):
    with s.db() as c:
        return collab.review(c, pid, oid, **body.model_dump())


@router.get('/{oid}/history')
def object_history(pid: str, oid: str):
    with s.db() as c:
        collab.load(c, pid, oid)
        return [{**dict(row), 'snapshot': json.loads(row['snapshot'])} for row in c.execute(
            'SELECT * FROM collaboration_history WHERE object_id=%s ORDER BY revision DESC LIMIT 100', (oid,))]


@router.post('/{oid}/restore')
def restore_object(pid: str, oid: str, body: Restore):
    with s.db() as c:
        return collab.restore(c, pid, oid, **body.model_dump())


@router.get('/{oid}/comments')
def object_comments(pid: str, oid: str):
    with s.db() as c:
        collab.load(c, pid, oid)
        return [dict(row) for row in c.execute(
            'SELECT * FROM collaboration_comments WHERE object_id=%s ORDER BY created,id LIMIT 500', (oid,))]


@router.post('/{oid}/comments', status_code=201)
def object_comment(pid: str, oid: str, body: Comment):
    with s.db() as c:
        return collab.comment(c, pid, oid, body.body)
