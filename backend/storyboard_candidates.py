"""Atomic import of a server-held storyboard candidate into owned objects.

The shot table is replaced, matching display IDs retain stable object/child IDs.
Existing visual cards, versions, voices, assets and timelines are never replaced.
"""
from copy import deepcopy
from fastapi import HTTPException
from . import collaboration as collab, platform_models, store as s
from .collaboration_validation import object_content,node_ids
from .production_context import read_project_state
from .prompts import validate_shots

SHOT_FIELDS={'id','uid','order','duration','scene','characters','action','emotion','camera','audio',
             'image_prompt','video_prompt','assetBindings','dialogues'}


def incoming(job):
    result=deepcopy(job['result'] or {})
    try:validate_shots(result,job['input'].get('target_duration'))
    except (ValueError,TypeError) as error:raise HTTPException(422,str(error)) from error
    return result


def prepared(state,result):
    """Remap candidate identities against the latest locked shared visual set."""
    from .film_bible.reuse import merge_candidate_visual
    existing=((state['document'].get('filmBible') or {}).get('visual') or {'cards':{},'versions':{}})
    candidate=((result.get('filmBible') or {}).get('visual') or {})
    try:
        visual,shots=merge_candidate_visual(existing,candidate,result['shots'])
    except (ValueError,TypeError) as error:
        raise HTTPException(422,str(error)) from error
    value=deepcopy(result);value['shots']=shots
    if candidate:
        value['filmBible']={**(value.get('filmBible') or {}),'visual':visual}
    return value


def impact(c,job):
    """Read-only comparison details; authoritative writes recheck frozen rows."""
    state=read_project_state(c,job['project_id']);result=prepared(state,incoming(job))
    ids={shot['id'] for shot in result['shots']}
    rows=[r for r in state['objects'] if r['kind']=='shot']
    removed=[r for r in rows if object_content(r)['shot']['id'] not in ids]
    actor=collab.live_principal(c)
    allowed=all(r['assignee_id']==actor.user_id for r in rows)
    if removed:
        from .identity import can_production
        allowed=allowed and can_production(c,actor,job['production_id'],'manager')
    return {'scope':'替换本集分镜表；已有视觉卡、音色、素材和剪辑保留',
            'shots':[collab.public(r) for r in rows],
            'removed_ids':[r['id'] for r in removed],
            'candidate_shot_count':len(result['shots']),
            'new_card_count':len(((result.get('filmBible') or {}).get('visual') or {}).get('cards') or {}),
            'can_replace_shots':allowed}


def update(row,content):
    return {'id':row['id'],'expected_revision':row['revision'],
            'assignment_epoch':row['assignment_epoch'],'content':content}


def new_node(kind,shot,document,models):
    model_id=((document.get('generationPolicy') or {}).get(kind) or {}).get('model_id','')
    model=next((m for m in models if m['id']==model_id),{})
    node_id=s.uid('node-')
    parameters=deepcopy(model.get('defaults') or {})
    if model:
        from .model_validation import shot_parameters
        # Creating editable nodes is not a paid submission. Derive published
        # shot controls now, but leave missing required user choices editable.
        parameters=shot_parameters(model,parameters,kind,{**document,'shots':[{**shot,kind+'Node':node_id}]},node_id,complete=False)
    return {'id':node_id,'type':'media','data':{
        'kind':kind,'label':shot['id']+(' · 分镜图' if kind=='image' else ' · 视频'),
        'prompt':shot[kind+'_prompt'],'model_id':model_id,
        'parameters':parameters,
        'model_capabilities':deepcopy(model.get('capabilities') or {}),
        'model_rules':deepcopy(model.get('rules') or {})}}


def adopt(c,job,body,locked,target):
    pid=job['project_id'];binding=job['collaboration'];result=incoming(job)
    state=read_project_state(c,pid)
    result=prepared(state,result)
    old_rows=[r for r in state['objects'] if r['kind']=='shot']
    if sorted(r['id'] for r in old_rows)!=binding['replacement_shots']:
        raise HTTPException(409,'本集镜头集合已变化，请重新生成分镜候选')
    # No unlock/relock with a different version: every row was part of the
    # initial sorted reference lock set in object_job_candidates.adopt.
    old_rows=[locked[r['id']] for r in old_rows]
    by_id={object_content(r)['shot']['id']:r for r in old_rows}
    if len(by_id)!=len(old_rows):raise HTTPException(422,'现有镜头显示编号重复，不能自动匹配替换')
    for row in old_rows:collab.editable(c,row)
    structure_row=next(r for r in locked.values() if r['kind']=='graph')
    structure=object_content(structure_row)
    creates=[];updates=[];deletes=[];shot_order=[];new_nodes=[];removed_nodes=set()
    models=platform_models.compiler_catalog()
    used=set()
    for index,raw in enumerate(result['shots']):
        previous=by_id.get(raw['id']);previous_content=object_content(previous) if previous else None
        shot=deepcopy(previous_content['shot']) if previous else {}
        shot.update({key:deepcopy(value) for key,value in raw.items() if key in SHOT_FIELDS})
        # Omitted optional candidate fields must not retain old bindings/dialogue.
        shot['assetBindings']=deepcopy(raw.get('assetBindings') or {'characters':[],'scene':None,'props':[]})
        shot['dialogues']=deepcopy(raw.get('dialogues') or [])
        shot['uid']=(previous_content['shot'].get('uid') or previous_content['shot']['id']) if previous else raw.get('uid') or s.uid('shot-')
        shot.update(storyboardNode=job['node_id'],order=index+1,prompts_need_review=False)
        children=[]
        for kind in ('image','video'):
            prior_id=(previous_content['shot'].get(kind+'Node') or (previous_content['shot'].get('pipeline') or {}).get(kind+'NodeId')) if previous else None
            child=next((deepcopy(n) for n in previous_content['nodes'] if n['id']==prior_id),None) if previous else None
            if child:
                data=child['data']
                # Follow a previously generated prompt, while preserving an
                # explicit manual node override and its selected model/settings.
                if not data.get('prompt') or data['prompt']==previous_content['shot'].get(kind+'_prompt'):
                    data['prompt']=shot[kind+'_prompt']
                data.update(
                    generation_revision=int(data.get('generation_revision') or 0)+1,
                    stale=bool(data.get('assetId') or data.get('resultJob')))
                if kind=='image':data['state_reviewed']=False
            else:
                child=new_node(kind,shot,state['document'],models);new_nodes.append(child['id'])
                structure['positions'][child['id']]={'x':1110 if kind=='image' else 1500,'y':80+index*320}
            children.append(child);shot[kind+'Node']=child['id']
        shot['pipeline']={**shot.get('pipeline',{}),'imageNodeId':shot['imageNode'],'videoNodeId':shot['videoNode']}
        content={'shot':shot,'nodes':children};shot_order.append(shot['uid'])
        if previous:used.add(previous['id']);updates.append(update(previous,content))
        else:creates.append({'kind':'shot','content':content})
        for source,dest in ((job['node_id'],shot['imageNode']),(shot['imageNode'],shot['videoNode'])):
            if not any(e['source']==source and e['target']==dest for e in structure['edges']):
                structure['edges'].append({'id':s.uid('edge-'),'source':source,'target':dest})
    for row in old_rows:
        if row['id'] not in used:
            deletes.append({'id':row['id'],'expected_revision':row['revision'],'assignment_epoch':row['assignment_epoch']})
            removed_nodes|=node_ids('shot',object_content(row))
    visual=((result.get('filmBible') or {}).get('visual') or {})
    cards=visual.get('cards') or {};versions=visual.get('versions') or {}
    existing_cards={object_content(r)['card']['id'] for r in state['objects'] if r['kind']=='visual_card'}
    if existing_cards&cards.keys():raise HTTPException(409,'候选视觉卡编号已存在，不能覆盖已有卡片')
    if any(v.get('cardId') not in cards for v in versions.values()):raise HTTPException(422,'候选视觉版本缺少所属卡片')
    for card_id,card in cards.items():
        creates.append({'kind':'visual_card','content':{'card':deepcopy(card),
            'versions':{vid:deepcopy(v) for vid,v in versions.items() if v['cardId']==card_id},'voice_profile':None}})
        new_nodes.extend('visual-version:'+vid for vid,v in versions.items() if v['cardId']==card_id)
    structure['edges']=[e for e in structure['edges'] if e['source'] not in removed_nodes and e['target'] not in removed_nodes]
    structure['positions']={nid:position for nid,position in structure['positions'].items() if nid not in removed_nodes}
    structure['nodeOrder']=list(dict.fromkeys([nid for nid in structure['nodeOrder'] if nid not in removed_nodes]+new_nodes))
    structure['shotOrder']=shot_order
    updates.append(update(structure_row,structure))
    source=object_content(target)
    if target['kind']!='node' or source['node']['data'].get('kind')!='storyboard':
        raise HTTPException(409,'分镜来源节点已变化')
    source['node']['data'].update(resultJob=job['id'],text=result.get('text') or s.dumps({'title':result['title'],'shots':result['shots']}),
        stale=source['node']['data'].get('prompt')!=job['input'].get('prompt') or
              source['node']['data'].get('generation_revision',0)!=job['input'].get('generation_revision',0),importedShotIds=shot_order)
    updates.append(update(target,source))
    changed=collab.commands(c,pid,creates=creates,updates=updates,deletes=deletes,_action='storyboard.adopt')
    return next(r for r in changed['updated'] if r['id']==target['id'])
