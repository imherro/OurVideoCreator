"""Business review inbox over existing script and asset revisions/history."""
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import Field

from . import business_roles as br, collaboration as collab, identity, store as s
from .collaboration_routes import StrictBody

router=APIRouter(prefix='/api/productions/{production_id}/workflow/reviews')


def approved_snapshot(c,row,*,version_id=None,voice=False,voice_profile=None):
    """Match immutable content, not today's card pointer or a bare status label."""
    current=identity.json_value(row['content'])
    from .voice_resolution import locked_versions,voice_snapshot
    value=(voice_snapshot(voice_profile or current.get('voice_profile')) if voice else current['versions'].get(version_id))
    if not value:raise HTTPException(409,'引用的共享资产版本不存在')
    for entry in c.execute('''SELECT revision,snapshot FROM collaboration_history
        WHERE object_id=%s AND snapshot->>'status'='completed' ORDER BY revision DESC''',(row['id'],)):
        snapshot=identity.json_value(entry['snapshot'])
        content=snapshot['content']
        approved=(locked_versions(content.get('voice_profile')).get(str(value.get('version'))) if voice
                  else content['versions'].get(version_id))
        if approved==value:
            return {'object_id':row['id'],'review_revision':entry['revision'],
                    'version_id':version_id,'voice':voice,'voice_version':value.get('version') if voice else None}
    raise HTTPException(409,'引用的共享资产版本尚未通过制片人验收，请先提交验收或继续使用已批准版本')


def generation_approvals(c,production_id,script,rows,target,mode,body,upstream):
    if not br.workflow(c,production_id) or mode in {'visual','voice','export'}:
        return None
    if mode!='storyboard' and body.kind not in {'image','video','audio'}:
        return None  # Prompt preparation does not need an approval stage.
    if not script or script['status']!='approved':
        raise HTTPException(409,'本集剧本尚未通过制片人验收，请先在剧本室提交')
    proof={'script_revision':script['revision'],'assets':[]}
    if mode=='storyboard':return proof  # Asset choice/preparation may follow script approval.
    versions={node.removeprefix('visual-version:') for node in upstream if node.startswith('visual-version:')}
    voice_uses=[]
    for row in rows:
        if row['kind']!='shot':continue
        shot=identity.json_value(row['content'])['shot'];bindings=shot.get('assetBindings') or {}
        for entry in [*(bindings.get('characters') or []),*(bindings.get('props') or []),bindings.get('scene')]:
            if isinstance(entry,dict) and entry.get('versionId'):versions.add(entry['versionId'])
        if body.kind in {'video','audio'}:
            voice_uses.extend((shot,item) for item in shot.get('dialogues',[]) if item.get('characterCardId') and str(item.get('text') or '').strip())
    cards=[row for row in rows if row['kind']=='visual_card']
    for version_id in sorted(versions):
        row=next((row for row in cards if version_id in identity.json_value(row['content'])['versions']),None)
        if not row:raise HTTPException(409,'引用的共享资产已不可用')
        proof['assets'].append(approved_snapshot(c,row,version_id=version_id))
    from .voice_resolution import resolved_voice,voice_document
    document=voice_document(cards)
    by_card={identity.json_value(row['content'])['card']['id']:row for row in cards}
    for shot,dialogue in voice_uses:
        voice_id,profile=resolved_voice(document,shot,dialogue)
        if not profile:
            if mode=='dialogue':raise HTTPException(409,'对白角色尚未配置可验收音色')
            continue  # Native video speech may have no separately configured voice.
        source=by_card.get(voice_id)
        if source:
            selected=identity.json_value(source['content'])['card']
            if selected.get('kind')=='character_state':source=by_card.get(selected.get('parentCardId'))
        if not source:raise HTTPException(409,'引用音色的父资产已不可用')
        approval=approved_snapshot(c,source,voice=True,voice_profile=profile)
        if approval not in proof['assets']:proof['assets'].append(approval)
    return proof


def scope(c,production_id):
    actor=collab.live_principal(c)
    identity.require_production(c,actor,production_id,'viewer')
    if not br.workflow(c,production_id):raise HTTPException(409,'作品尚未启用五角色流程')
    return actor


def inbox(c,production_id):
    actor=scope(c,production_id)
    scripts=[dict(row) for row in c.execute('''SELECT sc.project_id id,p.episode_no,p.episode_title,
        sc.title,sc.body,sc.status,sc.revision,sc.assignment_epoch,sc.assignee_id
        FROM episode_scripts sc JOIN projects p ON p.id=sc.project_id WHERE p.production_id=%s
        AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=p.id)
        ORDER BY p.episode_no,p.id''',(production_id,))]
    assets=[collab.public(row) for row in c.execute('''SELECT * FROM collaboration_objects
        WHERE production_id=%s AND kind='visual_card' AND NOT deleted ORDER BY created,id''',(production_id,))]
    return {'scripts':scripts,'assets':assets,'roles':sorted(br.roles(c,production_id,actor.user_id)),
            'actor_id':actor.user_id}


@router.get('')
def get_reviews(production_id:str):
    with s.db() as c:return inbox(c,production_id)


class AssetVersion(StrictBody):
    id:str
    revision:int=Field(ge=1)
    assignment_epoch:int=Field(ge=1)


class AssetReview(StrictBody):
    action:Literal['submit','approve','return']
    items:list[AssetVersion]=Field(min_length=1,max_length=200)


@router.post('/assets')
def review_assets(production_id:str,body:AssetReview):
    ids=[item.id for item in body.items]
    if len(ids)!=len(set(ids)):raise HTTPException(422,'不能重复选择同一资产')
    with s.db() as c:
        # The existing exclusive identity barrier gives the batch one atomic
        # staffing/content boundary; no jobs or external work inside this txn.
        identity.lock_identity_invariants(c)
        scope(c,production_id)
        br.require_role(c,production_id,'artist' if body.action=='submit' else 'producer')
        project=c.execute('''SELECT id FROM projects WHERE production_id=%s AND NOT EXISTS
            (SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=projects.id)
            ORDER BY episode_no,id LIMIT 1''',(production_id,)).fetchone()
        if not project:raise HTTPException(409,'作品没有可用分集')
        for item in sorted(body.items,key=lambda value:value.id):
            row=collab.load(c,project['id'],item.id,write=True)
            if row['kind']!='visual_card' or row['production_id']!=production_id:
                raise HTTPException(422,'验收清单只能包含本作品共享资产')
            collab.review(c,project['id'],item.id,expected_revision=item.revision,
                          assignment_epoch=item.assignment_epoch,action=body.action)
        return inbox(c,production_id)
