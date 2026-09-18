"""Business-facing production staffing commands. No generic permission editor."""
import time
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import Field

from . import business_roles as br, collaboration as collab, identity, store as s
from .collaboration_routes import StrictBody

router = APIRouter(prefix='/api/productions/{production_id}/workflow')


class Revision(StrictBody):
    revision: int = Field(ge=1)


class Member(Revision):
    roles: list[Literal['producer','writer','artist','generator','editor']] = Field(max_length=5)


class Default(Revision):
    role: Literal['writer','artist','editor']
    user_id: str | None


class Episode(Revision):
    role: Literal['writer','generator','editor']
    user_id: str | None
    confirm_special: bool = False


class Item(StrictBody):
    id: str
    revision: int = Field(ge=1)
    assignment_epoch: int = Field(ge=1)


class Bulk(Revision):
    kind: Literal['chapter','visual_card']
    items: list[Item] = Field(min_length=1,max_length=200)
    user_id: str | None


def view(c, production_id):
    principal=collab.live_principal(c)
    identity.require_production(c,principal,production_id,'viewer')
    config=br.workflow(c,production_id)
    business=br.roles(c,production_id,principal.user_id) if config else set()
    production=c.execute('SELECT id,name,workspace_id FROM productions WHERE id=%s',(production_id,)).fetchone()
    if not config:
        return {'enabled':False,'production':dict(production),
                'can_enable':identity.can_production(c,principal,production_id,'manager')}
    members=[dict(r) for r in c.execute('''SELECT u.id,u.nickname,u.is_active,pm.role legacy_role
        FROM production_members pm JOIN productions p ON p.id=pm.production_id
        JOIN workspace_members wm ON wm.workspace_id=p.workspace_id AND wm.user_id=pm.user_id
        JOIN users u ON u.id=pm.user_id WHERE pm.production_id=%s ORDER BY u.nickname,u.id''',(production_id,))]
    for member in members:member['roles']=sorted(br.roles(c,production_id,member['id']))
    episodes=[dict(r) for r in c.execute('''SELECT p.id,p.episode_no,p.episode_title,es.writer_id,es.generator_id,es.editor_id
        FROM projects p LEFT JOIN episode_staff es ON es.project_id=p.id WHERE p.production_id=%s
        AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=p.id)
        ORDER BY p.episode_no,p.id''',(production_id,))]
    for episode in episodes:
        episode['effective_writer_id']=br.default_assignee(c,production_id,'writer',project_id=episode['id'])
        episode['effective_editor_id']=br.default_assignee(c,production_id,'editor',project_id=episode['id'])
    items=[]
    for r in c.execute('''SELECT sc.id,sc.title,sc.revision,sc.assignment_epoch,sc.assignee_id,sd.title source_title
        FROM source_chapters sc JOIN source_documents sd ON sd.id=sc.source_id WHERE sd.production_id=%s
        AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE (d.kind='chapter' AND d.item_id=sc.id) OR (d.kind='source' AND d.item_id=sd.id))
        ORDER BY sd.created,sc.sort_order,sc.chapter_no''',(production_id,)):
        items.append({**dict(r),'kind':'chapter'})
    for r in c.execute("SELECT id,content,revision,assignment_epoch,assignee_id FROM collaboration_objects WHERE production_id=%s AND kind='visual_card' AND NOT deleted ORDER BY created,id",(production_id,)):
        card=identity.json_value(r['content'])['card']
        items.append({k:v for k,v in dict(r).items() if k!='content'} | {'kind':'visual_card','title':card.get('name') or card.get('title') or '未命名资产'})
    available=[]
    if 'producer' in business:
        available=[dict(r) for r in c.execute('''SELECT u.id,u.nickname FROM workspace_members wm JOIN users u ON u.id=wm.user_id
            WHERE wm.workspace_id=%s AND u.is_active ORDER BY u.nickname,u.id''',(production['workspace_id'],))]
    effective_defaults={role:br.default_assignee(c,production_id,role) for role in ('writer','artist','editor')}
    return {'enabled':True,'production':dict(production),'config':dict(config),'effective_defaults':effective_defaults,'my_roles':sorted(business),
            'can_manage':'producer' in business,'members':members,'available_members':available,'episodes':episodes,'items':items}


@router.get('')
def get_workflow(production_id:str):
    with s.db() as c:return view(c,production_id)


@router.post('/enable')
def enable(production_id:str):
    with s.db() as c:
        br.enable(c,production_id)
        return view(c,production_id)


@router.put('/members/{user_id}')
def member(production_id:str,user_id:str,body:Member):
    with s.db() as c:
        br._lock(c,production_id,body.revision)
        exists=c.execute('''SELECT 1 FROM workspace_members wm JOIN productions p ON p.workspace_id=wm.workspace_id
            JOIN users u ON u.id=wm.user_id WHERE p.id=%s AND wm.user_id=%s AND u.is_active''',(production_id,user_id)).fetchone()
        if not exists:raise HTTPException(422,'请先将有效账号加入作品所属团队')
        c.execute('''INSERT INTO production_members(production_id,user_id,role,created) VALUES(%s,%s,'viewer',%s)
            ON CONFLICT(production_id,user_id) DO NOTHING''',(production_id,user_id,time.time()))
        br.set_roles(c,production_id,user_id,body.roles,body.revision)
        return view(c,production_id)


@router.put('/defaults')
def defaults(production_id:str,body:Default):
    with s.db() as c:
        br.set_default(c,production_id,body.role,body.user_id,body.revision)
        return view(c,production_id)


@router.put('/episodes/{project_id}')
def episode(production_id:str,project_id:str,body:Episode):
    with s.db() as c:
        br.assign_episode(c,production_id,project_id,body.role,body.user_id,body.revision,confirm_special=body.confirm_special)
        return view(c,production_id)


@router.post('/assign')
def bulk(production_id:str,body:Bulk):
    with s.db() as c:
        br.assign_business_items(c,production_id,body.kind,[v.model_dump() for v in body.items],body.user_id,body.revision)
        return view(c,production_id)
