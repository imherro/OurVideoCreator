"""P5 candidates reuse durable jobs; no second queue or automatic publication.

The worker only computes a validated value. A short user-authorized transaction
checks the current target and writes the chosen result plus its adoption receipt.
"""
import json
import time
from fastapi import APIRouter, HTTPException
from pydantic import Field
from . import collaboration as collab, owned_content as owned, identity, store as s
from .collaboration_routes import StrictBody

router=APIRouter(prefix='/api/projects/{pid}/candidates')
RELATION_STAGES={'source_analysis':'chapter','script_generation':'script','adaptation_generation':'adaptation'}


def freeze_relation(c,pid,body):
    """Freeze current relational target after checking the submitted marker.

Callers build chapter/production snapshots while holding their domain locks;
generic job submission still revalidates markers, ownership and parent scope.
Other object kinds are cut over separately, never inferred from arbitrary IDs.
"""
    kind=RELATION_STAGES.get(body.input.get('stage'))
    markers=[key for key in ('source_event_extraction','episode_script_generation','adaptation_generation') if body.input.get(key)]
    if not kind:
        if markers:raise HTTPException(422,'生成阶段与目标类型不匹配')
        return {}
    if body.kind!='text' or len(markers)!=1 or any(body.input.get(key) is not None for key in ('visual_reference','voice_profile','dialogue')):
        raise HTTPException(422,'关系表生成必须声明单一文本目标')
    collab.lock_identity(c);scope=collab.project_scope(c,pid,'editor')
    production_id=scope['production_id'];marker=body.input[markers[0]]
    if not isinstance(marker,dict) or marker.get('productionId')!=production_id:
        raise HTTPException(422,'生成目标不属于当前作品')
    from .adaptation import adaptation_fingerprint,source_fingerprint,source_snapshot
    from .production_context import normalize_production_context
    if kind=='chapter':
        if markers!=['source_event_extraction'] or body.node_id!='source-chapter:'+str(marker.get('chapterId')):
            raise HTTPException(422,'章节目标与节点不匹配')
        row=owned.load(c,production_id,'chapter',marker.get('chapterId'),write=True)
        owned.authorize(c,row,marker.get('chapterRevision'),marker.get('assignmentEpoch'))
        return {'target':{'kind':kind,'id':row['id'],'revision':row['revision'],'assignment_epoch':row['assignment_epoch']}}
    # Lock production BEFORE script: source writes use chapter -> production ->
    # script when marking dependent scripts stale. Keep this same lock order.
    production=c.execute('SELECT * FROM productions WHERE id=%s FOR UPDATE',(production_id,)).fetchone()
    context=normalize_production_context(json.loads(production['shared_context']))
    if marker.get('adaptationFingerprint')!=adaptation_fingerprint(context):
        raise HTTPException(409,'改编规划已变化，请刷新后重新提交')
    if kind=='adaptation':
        identity.require_production(c,collab.live_principal(c),production_id,'manager')
        if markers!=['adaptation_generation'] or body.node_id!='adaptation:'+production_id:
            raise HTTPException(422,'改编目标与节点不匹配')
        if marker.get('sourceFingerprint')!=source_fingerprint(source_snapshot(c,production_id)):
            raise HTTPException(409,'原著事件已变化，请重新提交')
        return {'target':{'kind':kind,'id':production_id,'revision':production['revision'],'assignment_epoch':0}}
    if markers!=['episode_script_generation'] or body.node_id!='episode-script:'+pid:
        raise HTTPException(422,'正式剧本目标与节点不匹配')
    row=owned.load(c,production_id,'script',pid,write=True)
    owned.authorize(c,row,marker.get('scriptRevision'),marker.get('assignmentEpoch'))
    episode=c.execute('SELECT episode_no FROM projects WHERE id=%s',(pid,)).fetchone()
    if marker.get('episodeNo')!=episode['episode_no']:raise HTTPException(422,'目标分集编号不匹配')
    plan=next((p for p in context['episodePlans'] if p['episodeNo']==episode['episode_no']),None)
    if context['adaptationPlan']['status']!='approved' or not plan or plan['status']!='approved':
        raise HTTPException(409,'请先批准当前改编策划及分集规划')
    refs=[]
    for chapter_id in sorted(set(plan['sourceChapterRefs'])):
        chapter=owned.load(c,production_id,'chapter',chapter_id)
        refs.append({'id':chapter_id,'revision':chapter['revision'],'assignment_epoch':chapter['assignment_epoch']})
    if refs!=marker.get('chapterVersions'):raise HTTPException(409,'原著章节已变化，请重新提交')
    return {'target':{'kind':kind,'id':pid,'revision':row['revision'],'assignment_epoch':row['assignment_epoch']},
            'references':refs}


def adaptation_value(job,generated):
    """Pure validation against the submitted source IDs, never live writes."""
    from .adaptation import validate_adaptation_bundle
    bundle=validate_adaptation_bundle(generated,generated=True)
    marker=job['input'].get('adaptation_generation') or {}
    if bundle['adaptationPlan']['format']!=marker.get('format'):
        raise ValueError('模型返回的成片规格与任务提交规格不一致')
    if not set(bundle['adaptationPlan']['sourceEventIds'])<=set(marker.get('sourceEventIds') or []):
        raise ValueError('模型返回了任务快照中不存在的原著事件编号')
    if any(not set(plan['sourceChapterRefs'])<=set(marker.get('sourceChapterIds') or []) for plan in bundle['episodePlans']):
        raise ValueError('模型返回了任务快照中不存在的原著章节编号')
    return bundle


def load_job(c,pid,jid,*,write=False):
    collab.project_scope(c,pid)
    row=c.execute('SELECT * FROM jobs WHERE id=%s AND project_id=%s'+(' FOR UPDATE' if write else ''),(jid,pid)).fetchone()
    if not row:raise HTTPException(404,'候选任务不存在')
    job=s.unpack(row)
    if not job['collaboration'].get('target'):raise HTTPException(422,'此任务没有协作目标快照')
    return job


def current_target(c,job,*,write=False):
    target=job['collaboration']['target'];kind=target['kind'];production_id=job['production_id']
    if kind=='adaptation':
        owned.production_scope(c,production_id,write=write)
        row=c.execute('SELECT * FROM productions WHERE id=%s'+(' FOR UPDATE' if write else ''),(production_id,)).fetchone()
        if target['id']!=production_id:raise HTTPException(422,'改编候选归属无效')
        return row
    if kind in collab.KINDS:return collab.load(c,job['project_id'],target['id'],write=write)
    if kind not in ('chapter','script'):raise HTTPException(422,'此类候选采纳尚未接入')
    return owned.load(c,production_id,kind,target['id'],write=write)


def authorize_resume(c,job):
    """Polling preserves a remote handle; requeueing is a new generation action.

    Neither path grants the new assignee use of a predecessor's old ticket.
    A synchronous retry also needs its original content/references unchanged;
    otherwise the user must submit a fresh job from the current object.
    """
    collab.project_scope(c,job['project_id'],'editor')
    binding=job.get('collaboration') or {};target=binding.get('target')
    if not target:raise HTTPException(410,'旧任务没有对象权限快照；请从当前对象重新提交')
    if job.get('provider_job_id'):
        row=current_target(c,job,write=True)
        if target['kind']=='adaptation':
            identity.require_production(c,collab.live_principal(c),job['production_id'],'manager')
        else:
            collab.editable(c,row)
            collab.expected(row,row['revision'],target['assignment_epoch'])
        return
    from types import SimpleNamespace
    body=SimpleNamespace(kind=job['kind'],node_id=job['node_id'],input=job['input'])
    current=freeze_relation(c,job['project_id'],body)
    if not current:
        from .object_job_candidates import freeze
        current=freeze(c,job['project_id'],body)
    if current!={key:value for key,value in binding.items() if key!='adopted'}:
        raise HTTPException(409,'原任务目标、分配或引用已变化，请从当前对象重新提交，不能重排旧输入')


@router.get('/{jid}')
def preview(pid:str,jid:str):
    from .adaptation import adaptation_bundle
    with s.db() as c:
        job=load_job(c,pid,jid);row=current_target(c,job)
        value=({'revision':row['revision'],'assignment_epoch':0,**adaptation_bundle(json.loads(row['shared_context']))}
               if job['collaboration']['target']['kind']=='adaptation' else
               collab.public(row) if row['kind'] in collab.KINDS else owned.public(row))
        if job['collaboration']['target']['kind']=='chapter':
            value['events']=[{**dict(item),'characters':json.loads(item['characters']),'continuity':json.loads(item['continuity'])}
                for item in c.execute('SELECT * FROM source_events WHERE chapter_id=%s ORDER BY event_order',(row['id'],))]
        kind=job['collaboration']['target']['kind']
        actor=collab.live_principal(c)
        can_adopt=(identity.can_production(c,actor,job['production_id'],'manager') if kind=='adaptation' else
                   identity.can_production(c,actor,job['production_id'],'editor') and row['assignee_id']==actor.user_id)
        result={'job':job,'current':value,'can_adopt':can_adopt}
        if job['collaboration'].get('mode')=='storyboard' and job['status']=='succeeded':
            from .storyboard_candidates import impact
            result['impact']=impact(c,job)
            result['can_adopt']=can_adopt and result['impact']['can_replace_shots']
        return result


class Adopt(StrictBody):
    expected_revision:int=Field(ge=1)
    assignment_epoch:int=Field(ge=0)
    accept_stale:bool=False


def finish(c,job,body,result):
    target=job['collaboration']['target'];jid=job['id']
    receipt={'actor_user_id':identity.current().user_id,'revision':result['revision'],'created':time.time(),
             'from_revision':body.expected_revision,'accepted_stale':body.accept_stale}
    c.execute('UPDATE jobs SET collaboration=%s WHERE id=%s',(s.dumps({**job['collaboration'],'adopted':receipt}),jid))
    identity.audit(c,'candidate.adopt','job',jid,workspace_id=job['workspace_id'],production_id=job['production_id'],
        payload={'kind':target['kind'],'target_id':target['id'],**receipt})
    s.event(job['project_id'],{'type':'job','id':jid},connection=c)
    return {'target':result,'adopted':receipt}


@router.post('/{jid}/adopt')
def adopt(pid:str,jid:str,body:Adopt):
    from .adaptation import (adaptation_fingerprint,source_fingerprint,source_snapshot,save_script_row,
        validate_script,validate_source_references,_stale_scripts,_persist_production_context)
    from .production_context import normalize_production_context
    with s.db() as c:
        collab.lock_identity(c);collab.project_scope(c,pid,'editor')
        job=load_job(c,pid,jid,write=True)
        if job['status']!='succeeded':raise HTTPException(409,'任务尚未成功，不能采纳')
        if job['collaboration'].get('adopted'):raise HTTPException(409,'此候选已经采纳，不能重复应用')
        target=job['collaboration']['target'];kind=target['kind']
        if kind in collab.KINDS:
            from .object_job_candidates import adopt as adopt_object
            return finish(c,job,body,adopt_object(c,job,body))
        # Chapter writes already use chapter -> production -> script. For the
        # other relational types acquire production before the script row.
        production=None
        if kind in ('script','adaptation'):
            production=c.execute('SELECT * FROM productions WHERE id=%s FOR UPDATE',(job['production_id'],)).fetchone()
        row=current_target(c,job,write=True)
        if kind=='adaptation':
            identity.require_production(c,collab.live_principal(c),job['production_id'],'manager')
            if body.assignment_epoch!=0 or row['revision']!=body.expected_revision:raise HTTPException(409,'改编版本已变化')
        else:owned.authorize(c,row,body.expected_revision,body.assignment_epoch)
        if not body.accept_stale and (body.expected_revision!=target['revision'] or body.assignment_epoch!=target['assignment_epoch']):
            raise HTTPException(409,'目标已修改或重新分配；请先比较候选与当前内容，再明确采纳')
        if kind=='chapter':
            from .source_library import write_candidate_events
            owned.history_before(c,row,'candidate.adopt')
            write_candidate_events(c,job,job['result']['events'])
            c.execute("UPDATE source_chapters SET revision=revision+1,status='in_progress',updated_by=%s,updated=%s WHERE id=%s",
                      (identity.current().user_id,time.time(),row['id']))
            latest=owned.load(c,job['production_id'],'chapter',row['id'])
            owned.notify(c,latest,'candidate.adopt');result=owned.public(latest)
        elif kind=='script':
            context=normalize_production_context(json.loads(production['shared_context']))
            marker=job['input']['episode_script_generation']
            if adaptation_fingerprint(context)!=marker['adaptationFingerprint']:
                raise HTTPException(409,'分集规划已变化，请按新规划重新生成')
            for ref in job['collaboration'].get('references',[]):
                chapter=owned.load(c,job['production_id'],'chapter',ref['id'])
                collab.expected(chapter,ref['revision'],ref['assignment_epoch'])
            plan=next((p for p in context['episodePlans'] if p['episodeNo']==marker['episodeNo']),None)
            if context['adaptationPlan']['status']!='approved' or not plan or plan['status']!='approved':
                raise HTTPException(409,'改编规划已不再处于批准状态')
            validate_source_references(c,job['production_id'],plan['sourceChapterRefs'])
            value={**validate_script(job['result']['script']),'sourceChapterRefs':plan['sourceChapterRefs'],
                'storyGoal':plan['coreConflict'],'paywallBeat':{'role':plan['paywallRole'],'hook':plan['hook'],'cliffhanger':plan['cliffhanger']}}
            save_script_row(c,row,value,status='draft',generation_job_id=jid,actor_id=identity.current().user_id)
            latest=owned.load(c,job['production_id'],'script',row['id'])
            owned.notify(c,latest,'candidate.adopt');result=owned.public(latest)
        elif kind=='adaptation':
            marker=job['input']['adaptation_generation']
            if source_fingerprint(source_snapshot(c,job['production_id']))!=marker['sourceFingerprint']:
                raise HTTPException(409,'原著事件已变化，请按新原著重新生成')
            candidate=job['result']['adaptation']
            value=adaptation_value(job,{**candidate,
                'adaptationPlan':{k:v for k,v in candidate['adaptationPlan'].items() if k!='status'},
                'episodePlans':[{k:v for k,v in p.items() if k!='status'} for p in candidate['episodePlans']]})
            value['adaptationPlan']['status']='draft'
            for plan in value['episodePlans']:plan['status']='draft'
            validate_source_references(c,job['production_id'],[cid for p in value['episodePlans'] for cid in p['sourceChapterRefs']])
            context=normalize_production_context(json.loads(production['shared_context']));context.update(value)
            _stale_scripts(c,job['production_id']);revision=_persist_production_context(c,production,context)
            result={'revision':revision,**value}
            identity.audit(c,'adaptation.candidate.adopt','production',job['production_id'],
                workspace_id=job['workspace_id'],production_id=job['production_id'],payload={'revision':revision,'job_id':jid})
            for p in c.execute('SELECT id FROM projects WHERE production_id=%s',(job['production_id'],)):
                s.event(p['id'],{'type':'production','revision':revision},connection=c)
        else:raise HTTPException(422,'此类候选采纳尚未接入')
        return finish(c,job,body,result)
