"""Artist preparation of new assets from durable storyboard candidates."""
from copy import deepcopy
import hashlib
import json
import time

from fastapi import APIRouter, HTTPException
from pydantic import Field

from . import business_roles as br, collaboration as collab, identity, store as s
from .collaboration_routes import StrictBody
from .production_context import read_project_state
from .storyboard_candidates import incoming,prepared

router=APIRouter(prefix='/api/productions/{production_id}/workflow/asset-candidates')


def scope(c,production_id):
    actor=collab.live_principal(c)
    identity.require_production(c,actor,production_id,'viewer')
    if not br.workflow(c,production_id):raise HTTPException(409,'作品尚未启用五角色流程')
    return actor


def proposal(c,job):
    result=prepared(read_project_state(c,job['project_id']),incoming(job))
    visual=((result.get('filmBible') or {}).get('visual') or {'cards':{},'versions':{}})
    value={'job_id':job['id'],'project_id':job['project_id'],'visual':visual,
        'workflow_revision':br.workflow(c,job['production_id'])['revision']}
    fingerprint=hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return {**value,'fingerprint':fingerprint}


@router.get('')
def list_requests(production_id:str):
    with s.db() as c:
        actor=scope(c,production_id);rows=[]
        assigned=br.default_assignee(c,production_id,'artist')
        for row in c.execute('''SELECT j.*,p.episode_no,p.episode_title FROM jobs j JOIN projects p ON p.id=j.project_id
            WHERE j.production_id=%s AND j.kind='storyboard' AND j.status='succeeded'
            AND j.collaboration->>'mode'='storyboard' AND NOT (j.collaboration ? 'adopted')
            AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=p.id)
            ORDER BY j.created DESC''',(production_id,)):
            job=s.unpack(row)
            try:item=proposal(c,job)
            except HTTPException:continue  # Invalid legacy candidates are not artist work.
            if not item['visual']['cards']:continue
            rows.append({**item,'episode_no':row['episode_no'],'episode_title':row['episode_title']})
        return {'items':rows,'can_prepare':assigned==actor.user_id and 'artist' in br.roles(c,production_id,actor.user_id),
            'assignee_id':assigned}


class Prepare(StrictBody):
    fingerprint:str=Field(pattern=r'^[a-f0-9]{64}$')


@router.post('/{jid}')
def prepare(production_id:str,jid:str,body:Prepare):
    with s.db() as c:
        identity.lock_identity_invariants(c);actor=scope(c,production_id)
        br.require_role(c,production_id,'artist')
        if br.default_assignee(c,production_id,'artist')!=actor.user_id:
            raise HTTPException(403,'新增候选资产由作品默认资产师接手；请先在作品分工中明确默认资产师')
        row=c.execute('SELECT * FROM jobs WHERE id=%s AND production_id=%s FOR UPDATE',(jid,production_id)).fetchone()
        if not row:raise HTTPException(404,'分镜候选不存在')
        job=s.unpack(row);collab.project_scope(c,job['project_id'])
        if job['status']!='succeeded' or job['collaboration'].get('mode')!='storyboard' or job['collaboration'].get('adopted'):
            raise HTTPException(409,'该任务不是待处理的成功分镜候选')
        value=proposal(c,job)
        if value['fingerprint']!=body.fingerprint:raise HTTPException(409,'资产候选或分工已变化，请重新阅读')
        visual=value['visual'];creates=[]
        for card_id,card in visual['cards'].items():
            versions={vid:deepcopy(v) for vid,v in visual['versions'].items() if v['cardId']==card_id}
            for version in versions.values():version['status']='draft'
            creates.append({'kind':'visual_card','content':{'card':deepcopy(card),'versions':versions,'voice_profile':None}})
        if not creates:raise HTTPException(409,'候选资产已存在，请刷新后由抽卡师继续采纳分镜')
        changed=collab.commands(c,job['project_id'],creates=creates,updates=[],deletes=[],_action='storyboard.assets.prepare')
        previous=(job['collaboration'].get('asset_preparation') or {}).get('object_ids') or []
        receipt={'object_ids':sorted(set(previous)|{row['id'] for row in changed['created']}),
            'actor_id':actor.user_id,'created':time.time()}
        c.execute('UPDATE jobs SET collaboration=%s WHERE id=%s',(s.dumps({**job['collaboration'],'asset_preparation':receipt}),jid))
        identity.audit(c,'storyboard.assets.prepare','job',jid,production_id=production_id,payload={'count':len(creates)})
        s.event(job['project_id'],{'type':'job','id':jid},connection=c)
        return {'created_count':len(creates),'message':'已建立共享资产草稿；可继续编辑和提交验收，抽卡师现在可以采纳分镜'}
