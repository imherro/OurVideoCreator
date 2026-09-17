"""Frozen targets for existing canvas, shot, visual and voice generation paths."""
from copy import deepcopy
import json
import time
from fastapi import HTTPException
from . import collaboration as collab, owned_content as owned, store as s
from .collaboration_validation import object_content,node_ids
from .production_context import read_project_state


def ref(row):
    return {'kind':row['kind'],'id':row['id'],'revision':row['revision'],'assignment_epoch':row['assignment_epoch']}


def identify(rows,body):
    """Map real owned envelopes, never trust the caller's claimed object ID."""
    inp=body.input;nid=body.node_id
    if sum(inp.get(key) is not None for key in ('visual_reference','voice_profile','dialogue'))>1:
        raise HTTPException(422,'生成任务只能声明一种对象目标')
    if body.kind=='export':
        row=next((r for r in rows if r['kind']=='timeline'),None);mode='export'
    elif inp.get('visual_reference') is not None:
        marker=inp['visual_reference']
        if body.kind!='image' or not isinstance(marker,dict) or not isinstance(marker.get('versionId'),str) or not marker['versionId'] or nid!='visual-version:'+marker['versionId']:
            raise HTTPException(422,'视觉生成目标无效')
        row=next((r for r in rows if r['kind']=='visual_card' and marker['versionId'] in object_content(r)['versions']),None);mode='visual'
    elif inp.get('voice_profile') is not None:
        marker=inp['voice_profile']
        if body.kind!='audio' or not isinstance(marker,dict) or not isinstance(marker.get('cardId'),str) or not marker['cardId'] or nid!='voice-profile:'+marker['cardId']:
            raise HTTPException(422,'音色试听目标无效')
        row=next((r for r in rows if r['kind']=='visual_card' and object_content(r)['card']['id']==marker['cardId']),None);mode='voice'
    elif inp.get('dialogue') is not None:
        marker=inp['dialogue']
        if body.kind!='audio' or not isinstance(marker,dict) or not isinstance(marker.get('id'),str) or not marker['id'] or nid!='dialogue:'+marker['id']:
            raise HTTPException(422,'对白生成目标无效')
        row=next((r for r in rows if r['kind']=='shot' and str(object_content(r)['shot'].get('uid') or object_content(r)['shot']['id'])==marker.get('shotUid')),None);mode='dialogue'
    else:
        row=next((r for r in rows if nid in node_ids(r['kind'],object_content(r))),None)
        mode='storyboard' if body.kind=='storyboard' else 'node'
    if not row:raise HTTPException(404,'生成目标对象不存在；请先保存对象，不能向任意节点编号提交任务')
    if mode in ('node','storyboard'):
        value=object_content(row)
        node=value['node'] if row['kind']=='node' else next(n for n in value['nodes'] if n['id']==nid)
        if node['data'].get('kind')!=body.kind:raise HTTPException(422,'生成类型与目标节点不一致')
    return row,mode


def dependencies(state,target,mode,body):
    rows=state['objects'];selected={target['id']};content=object_content(target)
    graph=next(r for r in rows if r['kind']=='graph');structure=object_content(graph)
    upstream={body.node_id};grew=True
    while grew:
        parents={edge['source'] for edge in structure['edges'] if edge['target'] in upstream}
        grew=not parents<=upstream;upstream|=parents
    # An empty incoming-edge set is a dependency too: a new edge during
    # preparation must not silently change the meaning of the frozen prompt.
    if len(upstream)>1 or mode in ('node','storyboard'):selected.add(graph['id'])
    if mode=='storyboard':
        # Import replaces this episode's shot table. Freeze the complete prior
        # shot set plus owners of outgoing edges that a deletion could remove.
        prior_nodes=set()
        for row in rows:
            if row['kind']=='shot':
                selected.add(row['id']);prior_nodes|=node_ids('shot',object_content(row))
            elif row['kind']=='visual_card':
                # The first pass may reuse any production-wide visual identity,
                # not only cards already bound in this Episode.
                selected.add(row['id'])
        affected={e['target'] for e in structure['edges'] if e['source'] in prior_nodes}
        for row in rows:
            owned_nodes=node_ids(row['kind'],object_content(row))
            if row['kind']=='visual_card':owned_nodes={'visual-version:'+vid for vid in object_content(row)['versions']}
            if owned_nodes&affected:selected.add(row['id'])
    for row in rows:
        if node_ids(row['kind'],object_content(row))&upstream:selected.add(row['id'])
    versions=set(n.removeprefix('visual-version:') for n in upstream if n.startswith('visual-version:'))
    cards=set()
    for row in rows:
        if row['id'] not in selected:continue
        value=object_content(row)
        if row['kind']=='shot':
            shot=value['shot'];binding=shot.get('assetBindings') or {}
            for entry in [*(binding.get('characters') or []),*(binding.get('props') or []),binding.get('scene')]:
                if isinstance(entry,dict) and entry.get('versionId'):versions.add(entry['versionId'])
            cards.update(d.get('characterCardId') for d in shot.get('dialogues',[]) if isinstance(d,dict))
        elif row['kind']=='visual_card':
            for version in value['versions'].values():
                if version.get('parentVersionId'):versions.add(version['parentVersionId'])
    if mode=='dialogue':cards.add(body.input['dialogue'].get('characterCardId'))
    for row in rows:
        if row['kind']=='visual_card':
            value=object_content(row)
            if versions&value['versions'].keys() or value['card']['id'] in cards:selected.add(row['id'])
    # State selection is a reference to the parent's immutable voice library.
    parents={object_content(row)['card'].get('parentCardId') for row in rows
             if row['kind']=='visual_card' and row['id'] in selected}
    for row in rows:
        if row['kind']=='visual_card' and object_content(row)['card']['id'] in parents:selected.add(row['id'])
    return selected,upstream


def validate_audio(rows,target,mode,body):
    if mode not in ('voice','dialogue'):return
    inp=body.input
    if mode=='voice':
        profile=object_content(target)['voice_profile'];marker=inp['voice_profile']
        from .voice_reference_uploads import require_tts
        require_tts(profile)
        if not profile or profile.get('status')=='locked':raise HTTPException(422,'请先派生可编辑音色版本，再生成试听')
        if marker.get('version')!=profile.get('version'):raise HTTPException(409,'音色版本已变化')
        text=profile.get('previewText')
    else:
        marker=inp['dialogue'];shot=object_content(target)['shot']
        dialogue=next((d for d in shot.get('dialogues',[]) if d.get('id')==marker['id']),None)
        if not dialogue or dialogue.get('characterCardId')!=marker.get('characterCardId'):
            raise HTTPException(422,'对白不属于目标镜头或角色')
        from .voice_resolution import voice_document,resolved_voice
        voice_card,profile=resolved_voice(voice_document(rows),shot,dialogue)
        from .voice_reference_uploads import require_tts
        require_tts(profile)
        if (marker.get('voiceCardId') or marker['characterCardId'])!=voice_card:
            raise HTTPException(409,'角色状态音色已变化，请重新提交')
        if not profile or profile.get('status')!='locked':raise HTTPException(422,'对白须使用已锁定的角色音色')
        if marker.get('voiceVersion')!=profile.get('version') or marker.get('text')!=dialogue.get('text'):
            raise HTTPException(409,'对白或音色版本已变化')
        text=dialogue.get('text')
    if inp.get('model_id')!=profile.get('model_id') or inp.get('voice_type')!=profile.get('voiceType') or inp.get('prompt')!=text:
        raise HTTPException(422,'音频生成必须使用目标对象当前保存的文本、模型与音色')


def freeze(c,pid,body,state=None):
    collab.lock_identity(c);scope=collab.project_scope(c,pid,'editor')
    snapshot=state or read_project_state(c,pid)
    if not snapshot or not snapshot['project'].get('object_collaboration'):
        raise HTTPException(410,'旧工程没有协作对象目标；请新建协作工程')
    target,mode=identify(snapshot['objects'],body)
    selected,upstream=dependencies(snapshot,target,mode,body)
    # Metadata -> canonical script -> sorted object rows agrees with existing
    # promotion and source/production invalidation order. No HTTP in these locks.
    production=c.execute('SELECT revision FROM productions WHERE id=%s FOR SHARE',(scope['production_id'],)).fetchone()
    project=c.execute('SELECT revision FROM projects WHERE id=%s FOR SHARE',(pid,)).fetchone()
    if production['revision']!=snapshot['production']['revision'] or project['revision']!=snapshot['project']['revision']:
        raise HTTPException(409,'作品设置在生成准备期间已变化，请重新提交')
    script=c.execute('SELECT * FROM episode_scripts WHERE project_id=%s FOR SHARE',(pid,)).fetchone()
    script_ref=None
    if script and json.loads(script['metadata']).get('projectionNodeId') in upstream:
        saved=snapshot.get('script')
        if not saved or saved['revision']!=script['revision'] or saved['assignment_epoch']!=script['assignment_epoch']:
            raise HTTPException(409,'正式剧本在生成准备期间已变化，请重新提交')
        script_ref={'kind':'script','id':pid,'revision':script['revision'],'assignment_epoch':script['assignment_epoch']}
    prior={r['id']:r for r in snapshot['objects']}
    locked={oid:collab.load(c,pid,oid,write=True) for oid in sorted(selected)}
    for oid,row in locked.items():collab.expected(row,prior[oid]['revision'],prior[oid]['assignment_epoch'])
    visual_catalog_objects=None
    if mode=='storyboard':
        # Follow collaboration.commands lock order: object rows first, then the
        # production visual binding guard. Re-read the identity set so a card
        # created between the initial projection and row locks cannot be missed.
        c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                  ('visual-bindings:'+scope['production_id'],))
        visual_catalog_objects=sorted(row['id'] for row in c.execute(
            "SELECT id FROM collaboration_objects WHERE production_id=%s AND kind='visual_card' AND NOT deleted",
            (scope['production_id'],)))
        expected_catalog=sorted(r['id'] for r in snapshot['objects'] if r['kind']=='visual_card')
        if visual_catalog_objects!=expected_catalog:
            raise HTTPException(409,'作品视觉资产在生成准备期间已变化，请重新提交')
        visual=deepcopy(((snapshot['document'].get('filmBible') or {}).get('visual') or {'cards':{},'versions':{}}))
        body.input={**body.input,'storyboard_visual_context':{
            'version':'production-visual-reuse/v1',
            'production_id':scope['production_id'],
            'production_revision':production['revision'],
            'visual':visual,
        }}
    target=locked[target['id']];collab.editable(c,target)
    validate_audio(list(locked.values()),target,mode,body)
    binding={'target':ref(target),'mode':mode,'references':[ref(r) for oid,r in locked.items() if oid!=target['id']],
             'script_reference':script_ref,'project_revision':project['revision'],'production_revision':production['revision']}
    if mode=='storyboard':binding['replacement_shots']=sorted(r['id'] for r in snapshot['objects'] if r['kind']=='shot')
    if mode=='storyboard':binding['visual_catalog_objects']=visual_catalog_objects
    return binding


def lock_batch(c,pid,bodies,state):
    """Prelock the union so reversed batch orders cannot deadlock mid-batch."""
    collab.lock_identity(c);scope=collab.project_scope(c,pid,'editor')
    selected=set()
    for body in bodies:
        target,mode=identify(state['objects'],body)
        ids,_=dependencies(state,target,mode,body);selected|=ids
    c.execute('SELECT id FROM productions WHERE id=%s FOR SHARE',(scope['production_id'],)).fetchone()
    c.execute('SELECT id FROM projects WHERE id=%s FOR SHARE',(pid,)).fetchone()
    c.execute('SELECT project_id FROM episode_scripts WHERE project_id=%s FOR SHARE',(pid,)).fetchone()
    for oid in sorted(selected):collab.load(c,pid,oid,write=True)


def adopt(c,job,body):
    """Apply a selected server-held result; no caller-supplied content patch."""
    binding=job['collaboration'];target=binding['target'];mode=binding['mode'];pid=job['project_id']
    if mode=='export':raise HTTPException(422,'导出仅登记素材，无需写回创作对象')
    if mode=='storyboard' and 'replacement_shots' not in binding:
        raise HTTPException(410,'旧分镜候选没有完整镜头版本快照，请重新生成')
    if mode=='storyboard' and ('visual_catalog_objects' not in binding or
            not (job['input'].get('storyboard_visual_context') or {}).get('version')):
        raise HTTPException(410,'旧分镜候选没有完整视觉目录快照，请重新生成')
    production=c.execute('SELECT revision FROM productions WHERE id=%s FOR SHARE',(job['production_id'],)).fetchone()
    project=c.execute('SELECT revision FROM projects WHERE id=%s FOR SHARE',(pid,)).fetchone()
    if production['revision']!=binding['production_revision'] or project['revision']!=binding['project_revision']:
        raise HTTPException(409,'生成所用作品设置已变化，请重新生成')
    script_ref=binding.get('script_reference')
    if script_ref:
        script=owned.load(c,job['production_id'],'script',script_ref['id'],write=True)
        collab.expected(script,script_ref['revision'],script_ref['assignment_epoch'])
    refs={r['id']:r for r in binding.get('references',[])}
    locked={oid:collab.load(c,pid,oid,write=True) for oid in sorted({target['id'],*refs})}
    for oid,r in refs.items():collab.expected(locked[oid],r['revision'],r['assignment_epoch'])
    if mode=='storyboard':
        c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                  ('visual-bindings:'+job['production_id'],))
        current_visual_ids=sorted(item['id'] for item in c.execute(
            "SELECT id FROM collaboration_objects WHERE production_id=%s AND kind='visual_card' AND NOT deleted",
            (job['production_id'],)))
        if current_visual_ids!=binding['visual_catalog_objects']:
            raise HTTPException(409,'作品视觉资产集合已变化，请重新生成分镜候选')
    row=locked[target['id']];collab.editable(c,row);collab.expected(row,body.expected_revision,body.assignment_epoch)
    if not body.accept_stale and (body.expected_revision!=target['revision'] or body.assignment_epoch!=target['assignment_epoch']):
        raise HTTPException(409,'目标已变化，请比较候选后明确采纳旧结果')
    if mode=='storyboard':
        from .storyboard_candidates import adopt as adopt_storyboard
        return adopt_storyboard(c,job,body,locked,row)
    content=object_content(row);inp=job['input'];result=job['result']
    asset=None
    if job['kind'] in ('image','video','audio'):
        returned=next((a for a in result.get('assets',[]) if a.get('kind')==job['kind']),None)
        if not returned:raise HTTPException(422,'候选没有预期类型的素材')
        asset=c.execute('''SELECT * FROM assets WHERE id=%s AND project_id=%s AND kind=%s
            AND NOT EXISTS(SELECT 1 FROM deleted_items WHERE kind='asset' AND item_id=assets.id)''',
            (returned['id'],pid,job['kind'])).fetchone()
        if not asset or json.loads(asset['metadata']).get('job_id')!=job['id']:
            raise HTTPException(422,'候选素材已删除或不属于该任务')
    if mode=='node':
        node=content['node'] if row['kind']=='node' else next((n for n in content['nodes'] if n['id']==job['node_id']),None)
        if not node or node['data'].get('kind')!=job['kind']:raise HTTPException(409,'目标节点已变化')
        data=node['data'];data['resultJob']=job['id']
        projection=inp.get('shot_video_projection')
        if job['kind']=='video' and isinstance(projection,dict) and projection.get('version')=='shot-video/v1' and 'sourcePrompt' in projection:
            prompt_changed=data.get('prompt')!=projection['sourcePrompt']
        else:
            prompt_changed=(not inp.get('reference_compiler') and not inp.get('dialogue_projection')
                            and data.get('prompt')!=inp.get('prompt'))
        data['stale']=prompt_changed or data.get('generation_revision',0)!=inp.get('generation_revision',0)
        if job['kind']=='text':data['text']=str(result.get('text') or '')
        elif asset:
            data['assetId']=asset['id']
            if inp.get('generation_fingerprint'):data['generationFingerprint']=inp['generation_fingerprint']
            if job['kind']=='image':data['state_reviewed']=False
        else:raise HTTPException(422,'候选内容类型无效')
    elif mode=='visual':
        marker=inp['visual_reference'];version=content['versions'].get(marker['versionId'])
        if not version or version.get('status') not in ('draft','pending_reference'):
            raise HTTPException(409,'视觉版本已锁定、弃用或不存在，请先派生新版本')
        generation={'jobId':job['id'],'submissionId':job['submission_id'],'model_id':inp['model_id'],
            'prompt':inp['prompt'],'targetSource':marker.get('targetSource'),
            **{k:marker[k] for k in ('parentVersionId','parentReferenceAssetId') if marker.get(k)}}
        reference={'role':'primary','assetId':asset['id'],'source':'generated','createdAt':int(time.time()*1000),'provenance':generation}
        version['references']=[r for r in version.get('references',[]) if r.get('role')!='primary']+[reference]
        version['status']='pending_reference'
        version['provenance']={**version.get('provenance',{}),'primaryReference':generation,
                               'referenceGeneration':{**generation,'status':'succeeded'}}
    elif mode=='voice':
        profile=content.get('voice_profile')
        if not profile or profile.get('status')=='locked' or profile.get('version')!=inp['voice_profile']['version']:
            raise HTTPException(409,'音色版本已变化或锁定，请先派生可编辑版本')
        if profile.get('model_id')!=inp['model_id'] or profile.get('voiceType')!=inp['voice_type']:
            raise HTTPException(409,'音色身份已变化，不能采纳其他音色的试听')
        from .voice_identity import validate_adoption
        validate_adoption(c,target,profile)
        profile.update(previewAssetId=asset['id'],generationJobId=job['id'])
    elif mode=='dialogue':
        marker=inp['dialogue'];dialogue=next((d for d in content['shot'].get('dialogues',[]) if d.get('id')==marker['id']),None)
        if not dialogue or dialogue.get('text')!=marker['text'] or dialogue.get('characterCardId')!=marker['characterCardId']:
            raise HTTPException(409,'对白文字或角色已变化，不能采纳旧台词音频')
        from types import SimpleNamespace
        validate_audio(read_project_state(c,pid)['objects'],row,'dialogue',SimpleNamespace(input=inp))
        dialogue.update(audioAssetId=asset['id'],audioJobId=job['id'],audioVoiceVersion=marker['voiceVersion'])
    else:raise HTTPException(422,'候选类型无效')
    return collab.commands(c,pid,creates=[],deletes=[],updates=[{'id':row['id'],
        'expected_revision':body.expected_revision,'assignment_epoch':body.assignment_epoch,'content':content}],
        _action='candidate.adopt')['updated'][0]
