"""Versioned review workflow on real PostgreSQL and actual local media."""
from tests.test_episode_samples import clip,setup,upload
from tests.test_business_roles import change_roles
from tests.test_p5_object_transactions import team,admin,clients,clear_auth_rate_limits


def send(team,path,sid,kind,client=None,**fields):
    who=client or team['admin'];url=path+'/'+sid+'/review-events'
    state=who.get(url).json()
    body={key:state[key] for key in ('revision','latest_id','staffing_revision')}
    body.update(kind=kind,**fields)
    return who.post(url,json=body)


def test_comment_reply_new_version_resolve_and_approve(team,clip):
    path,delivery=setup(team);one=upload(team,path,delivery,clip).json()['id']
    result=send(team,path,one,'comment',frame=12,body='此帧转场太快')
    assert result.status_code==201,result.text
    comment=result.json()['events'][0]
    assert comment['frame']==12 and comment['sample_id']==one
    assert send(team,path,one,'approve').status_code==409
    assert send(team,path,one,'return',body='请按批注修改').json()['status']=='return'
    two=upload(team,path,delivery,clip).json()['id']
    result=send(team,path,one,'reply',client=team['b'],parent_id=comment['id'],related_sample_id=two,body='V2 已放慢转场')
    assert result.status_code==201,result.text
    assert send(team,path,two,'approve').status_code==409
    assert send(team,path,one,'resolve',parent_id=comment['id']).status_code==201
    assert send(team,path,one,'approve').status_code==409
    assert send(team,path,two,'approve').json()['status']=='approve'
    old=team['admin'].get(path+'/'+one+'/review-events').json()
    assert old['events'][0]['frame']==12 and old['events'][0]['sample_id']==one
    assert old['status']=='return'
    # Reopening a previously resolved concern invalidates current approval.
    assert send(team,path,one,'reopen',parent_id=comment['id']).status_code==201
    assert team['admin'].get(path+'/'+two+'/review-events').json()['status']=='pending'


def test_stale_approval_and_role_boundaries(team,clip):
    path,delivery=setup(team);sid=upload(team,path,delivery,clip).json()['id'];url=path+'/'+sid+'/review-events'
    before=team['admin'].get(url).json()
    for client in (team['a'],team['b']):
        assert send(team,path,sid,'comment',client=client,frame=0,body='不应允许').status_code==403
        assert send(team,path,sid,'approve',client=client).status_code==403
    assert send(team,path,sid,'comment',frame=30,body='越界').status_code==422
    response=send(team,path,sid,'comment',frame=0,body='请修改');assert response.status_code==201,response.text
    parent=response.json()['events'][0]['id']
    stale={key:before[key] for key in ('revision','latest_id','staffing_revision')}
    assert team['admin'].post(url,json={**stale,'kind':'approve'}).status_code==409
    assert send(team,path,sid,'reply',client=team['a'],parent_id=parent,body='越权').status_code==403
    change_roles(team,team['bid'],[])
    assert send(team,path,sid,'reply',client=team['b'],parent_id=parent,body='旧负责人').status_code==403


def test_upload_invalidates_old_page_and_new_version_starts_unapproved(team,clip):
    path,delivery=setup(team);one=upload(team,path,delivery,clip).json()['id'];url=path+'/'+one+'/review-events'
    assert send(team,path,one,'approve').json()['status']=='approve'
    before=team['admin'].get(url).json()
    two=upload(team,path,delivery,clip).json()['id']
    assert team['admin'].get(path+'/'+two+'/review-events').json()['status']=='pending'
    assert team['admin'].get(url).json()['status']=='approve'
    assert send(team,path,two,'comment',frame=1,body='新版问题').status_code==201
    assert team['admin'].get(url).json()['status']=='approve'
    stale={key:before[key] for key in ('revision','latest_id','staffing_revision')}
    assert team['admin'].post(url,json={**stale,'kind':'return','body':'旧页面'}).status_code==409


def test_cross_episode_parent_and_revoked_then_restored_role_are_rejected(team,clip):
    path,delivery=setup(team);one=upload(team,path,delivery,clip).json()['id']
    comment=send(team,path,one,'comment',frame=2,body='测试批注').json()['events'][0]['id']
    two=upload(team,path,delivery,clip).json()['id']
    assert send(team,path,two,'resolve',parent_id=comment).status_code==422
    assert send(team,path,one,'reply',client=team['b'],parent_id=comment,body='已改',related_sample_id='missing').status_code==404
    url=path+'/'+one+'/review-events';before=team['b'].get(url).json()
    change_roles(team,team['bid'],[]);change_roles(team,team['bid'],['editor'])
    body={key:before[key] for key in ('revision','latest_id','staffing_revision')}
    assert team['b'].post(url,json={**body,'kind':'reply','parent_id':comment,'body':'旧票据'}).status_code==409
    other=team['admin'].post('/api/projects',json={'name':'another review','five_role_workflow':True}).json()
    assert team['admin'].get('/api/projects/'+other['id']+'/samples/'+one+'/review-events').status_code==404
