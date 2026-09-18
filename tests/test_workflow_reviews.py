"""R2 reviews reuse canonical objects and immutable history on real PostgreSQL."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from fastapi import HTTPException

from backend import store as s
from tests.test_business_roles import enable,change_roles,actor,assign
from tests.test_p5_object_transactions import team,admin,clients,clear_auth_rate_limits,url,save


def card(team,key,voice_profile=None):
    content={'card':{'id':key,'name':'角色 '+key,'kind':'character','currentVersionId':key+'-v1','parentCardId':None,'status':'active'},
        'versions':{key+'-v1':{'id':key+'-v1','cardId':key,'version':1,'parentVersionId':None,'status':'draft',
            'spec':{'description':'初版人物设定','attributes':[]},'invariants':[],'references':[],'createdAt':1,'provenance':{}}},
        'voice_profile':voice_profile}
    response=team['a'].post(url(team),json={'kind':'visual_card','content':content})
    assert response.status_code==201,response.text
    return response.json()


def endpoint(team):return '/api/productions/'+team['production']+'/workflow/reviews'


def review(team,rows,action,client=None):
    return (client or team['a']).post(endpoint(team)+'/assets',json={'action':action,
        'items':[{k:row[k] for k in ('id','revision','assignment_epoch')} for row in rows]})


def setup(team):
    enable(team)
    change_roles(team,team['aid'],['artist'])
    change_roles(team,team['bid'],['artist'])
    # Two artists have no implicit default: explicitly choose the first for new cards.
    state=team['admin'].get('/api/productions/'+team['production']+'/workflow').json()
    result=team['admin'].put('/api/productions/'+team['production']+'/workflow/defaults',json={
        'revision':state['config']['revision'],'role':'artist','user_id':team['aid']})
    assert result.status_code==200,result.text


def test_assets_submit_owner_only_producer_approves_exact_version(team):
    setup(team);row=card(team,'lead')
    assert review(team,[row],'submit',team['b']).status_code==403
    assert review(team,[row],'approve',team['a']).status_code==403
    response=review(team,[row],'submit');assert response.status_code==200,response.text
    pending=response.json()['assets'][0]
    assert pending['status']=='pending_review'
    assert review(team,[row],'approve',team['admin']).status_code==409
    approved=review(team,[pending],'approve',team['admin'])
    assert approved.status_code==200,approved.text
    approved=approved.json()['assets'][0]
    assert approved['status']=='completed'
    edited=deepcopy(approved['content']);edited['versions']['lead-v1']['spec']['description']='修订人物设定'
    response=save(team,approved,edited);assert response.status_code==200,response.text
    assert response.json()['status']=='in_progress'
    history=team['a'].get(url(team,row,'/history')).json()
    assert any(item['snapshot']['status']=='completed' for item in history)


def test_asset_review_batch_conflict_rolls_back_entire_batch(team):
    setup(team);rows=[card(team,'first'),card(team,'second')]
    pending=review(team,rows,'submit').json()['assets']
    stale=deepcopy(pending);stale[-1]['revision']-=1
    before=team['admin'].get(endpoint(team)).json()
    assert review(team,stale,'approve',team['admin']).status_code==409
    assert team['admin'].get(endpoint(team)).json()==before
    with s.db() as c:
        assert c.execute("SELECT count(*) n FROM collaboration_history WHERE action='review.approve' AND object_id=ANY(%s)",
            ([row['id'] for row in rows],)).fetchone()['n']==0
    response=review(team,pending,'return',team['admin'])
    assert response.status_code==200,response.text
    assert all(row['status']=='returned' for row in response.json()['assets'])


def test_old_approved_asset_version_remains_usable_but_new_version_needs_review(team):
    from backend.workflow_reviews import approved_snapshot
    setup(team);row=card(team,'hero')
    pending=review(team,[row],'submit').json()['assets'][0]
    approved=review(team,[pending],'approve',team['admin']).json()['assets'][0]
    content=deepcopy(approved['content'])
    content['versions']['hero-v2']={**deepcopy(content['versions']['hero-v1']),'id':'hero-v2',
        'version':2,'parentVersionId':'hero-v1'}
    content['versions']['hero-v2']['spec']['description']='新的设计'
    content['card']['currentVersionId']='hero-v2'
    response=save(team,approved,content);assert response.status_code==200,response.text
    row=response.json()
    with s.db() as c:
        assert approved_snapshot(c,row,version_id='hero-v1')['review_revision']==approved['revision']
        with pytest.raises(HTTPException) as error:approved_snapshot(c,row,version_id='hero-v2')
        assert error.value.status_code==409


def test_generator_freeze_requires_approved_script_but_artist_preparation_is_exempt(team):
    from backend.object_job_candidates import freeze
    from backend.workflow_reviews import generation_approvals
    setup(team)
    change_roles(team,team['bid'],['generator'])
    assign(team,team['bid'],confirm_special=True)
    result=team['b'].post(url(team),json={'kind':'node','content':{'node':{
        'id':'r2-image','type':'media','data':{'kind':'image','prompt':'test'}}}})
    assert result.status_code==201,result.text
    body=SimpleNamespace(kind='image',node_id='r2-image',input={})
    with actor(team['b']),s.db() as c:
        with pytest.raises(HTTPException) as error:freeze(c,team['pid'],body)
        assert error.value.status_code==409
        assert '剧本' in error.value.detail
    # The exemption is specific to an actual asset-target mode, not caller input.
    with s.db() as c:
        assert generation_approvals(c,team['production'],None,[],None,'visual',body,set()) is None


def test_state_voice_uses_approved_parent_version_not_parent_draft(team):
    from backend.workflow_reviews import generation_approvals
    setup(team)
    profile={'cardId':'speaker','version':1,'status':'locked','voiceType':'test-voice'}
    parent=card(team,'speaker',profile)
    pending=review(team,[parent],'submit').json()['assets'][0]
    parent=review(team,[pending],'approve',team['admin']).json()['assets'][0]
    parent['content']['voice_profile']={**profile,'version':2,'voiceType':'new-unapproved',
        'lockedVersions':{'1':deepcopy(profile)}}
    child={'id':'child-object','kind':'visual_card','content':{'card':{
        'id':'speaker-state','kind':'character_state','parentCardId':'speaker','voiceVersion':1},'versions':{},'voice_profile':None}}
    shot={'id':'shot-object','kind':'shot','content':{'shot':{'dialogues':[{
        'id':'line','characterCardId':'speaker-state','text':'hello'}]}}}
    body=SimpleNamespace(kind='audio',input={})
    with s.db() as c:
        proof=generation_approvals(c,team['production'],{'status':'approved','revision':3},
            [parent,child,shot],shot,'dialogue',body,set())
        assert proof['assets'][0]['object_id']==parent['id']
        assert proof['assets'][0]['voice_version']==1
        child['content']['card']['voiceVersion']=2
        with pytest.raises(HTTPException) as error:
            generation_approvals(c,team['production'],{'status':'approved','revision':3},
                [parent,child,shot],shot,'dialogue',body,set())
        assert error.value.status_code==409


def test_script_business_review_does_not_require_planning_approval_and_rejects_stale(team):
    from backend import business_roles as br
    from backend.adaptation import SCRIPT_FIELDS
    enable(team)
    change_roles(team,team['aid'],['writer'])
    with actor(team['admin']),s.db() as c:
        br.assign_episode(c,team['production'],team['pid'],'writer',team['aid'],
            br.workflow(c,team['production'])['revision'])
    path='/api/productions/'+team['production']+'/episode-scripts/1'
    row=team['a'].get(path).json()
    def edit(row,text):
        payload={key:row[key] for key in SCRIPT_FIELDS}
        payload.update(body=text,revision=row['revision'],assignment_epoch=row['assignment_epoch'])
        result=team['a'].put(path,json=payload)
        assert result.status_code==200,result.text
        return result.json()
    def command(row,action,client):
        return client.post(path+'/'+action,json={key:row[key] for key in ('revision','assignment_epoch')})
    row=edit(row,'外景，雨夜。小林：车来了。')
    pending=command(row,'review',team['a'])
    assert pending.status_code==200,pending.text
    pending=pending.json()
    assert command(pending,'approve',team['a']).status_code==403
    approved=command(pending,'approve',team['admin'])
    assert approved.status_code==200,approved.text
    assert approved.json()['status']=='approved'
    revised=edit(approved.json(),'外景，雨夜。小林：车还没有来。')
    assert revised['status']=='draft'
    assert command(pending,'approve',team['admin']).status_code==409
    assert team['admin'].get(path).json()['status']=='draft'
