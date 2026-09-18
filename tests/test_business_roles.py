"""R1 role foundation on isolated PostgreSQL, never live acceptance data."""
from contextlib import contextmanager

import pytest
from fastapi import HTTPException

from backend import business_roles as br, identity, store as s
from tests.test_p5_object_transactions import team, admin, clients, clear_auth_rate_limits, create, url, save


@contextmanager
def actor(client):
    with s.db() as c:
        row = c.execute('''SELECT u.id,u.phone,u.nickname,u.platform_role,se.token_hash,se.expires
            FROM sessions se JOIN users u ON u.id=se.user_id WHERE se.token_hash=%s''',
            (identity.digest(client.cookies.get(identity.SESSION_COOKIE)),)).fetchone()
    token = identity.set_current(identity.Principal(row['id'], row['phone'], row['nickname'],
                                                   row['platform_role'], row['token_hash'], row['expires']))
    try:
        yield row['id']
    finally:
        identity.reset_current(token)


def enable(team):
    with actor(team['admin']), s.db() as c:
        return br.enable(c, team['production'])


def change_roles(team, user_id, roles):
    with actor(team['admin']), s.db() as c:
        revision = br.workflow(c, team['production'])['revision']
        return br.set_roles(c, team['production'], user_id, roles, revision)


def assign(team, user_id, **extra):
    with actor(team['admin']), s.db() as c:
        revision = br.workflow(c, team['production'])['revision']
        return br.assign_episode(c, team['production'], team['pid'], 'generator', user_id, revision, **extra)


def test_enable_preserves_all_objects_and_does_not_grant_workspace_owner(team):
    shot = create(team)
    before = team['admin'].get(url(team)).json()
    enable(team)
    assert team['admin'].get(url(team)).json() == before
    change_roles(team, team['aid'], ['producer', 'writer'])
    with s.db() as c:
        assert br.roles(c, team['production'], team['aid']) == {'producer', 'writer'}
        assert c.execute('SELECT role FROM workspace_members WHERE workspace_id=%s AND user_id=%s',
                         (team['workspace'], team['aid'])).fetchone()['role'] == 'member'
        assert c.execute('SELECT role FROM production_members WHERE production_id=%s AND user_id=%s',
                         (team['production'], team['aid'])).fetchone()['role'] == 'editor'
        assert c.execute('SELECT assignee_id FROM collaboration_objects WHERE id=%s', (shot['id'],)).fetchone()['assignee_id'] == team['aid']


def test_default_is_explicit_with_multiple_people_and_does_not_reassign(team):
    before = team['admin'].get(url(team)).json()
    enable(team)
    change_roles(team, team['aid'], ['writer', 'artist'])
    with s.db() as c:
        assert br.default_assignee(c, team['production'], 'writer') == team['aid']
        assert br.default_assignee(c, team['production'], 'generator', project_id=team['pid']) is None
    change_roles(team, team['bid'], ['writer'])
    with actor(team['admin']), s.db() as c:
        assert br.default_assignee(c, team['production'], 'writer') is None
        br.set_default(c, team['production'], 'writer', team['bid'], br.workflow(c, team['production'])['revision'])
        assert br.default_assignee(c, team['production'], 'writer') == team['bid']
    assert team['admin'].get(url(team)).json() == before


def test_atomic_episode_transfer_requires_confirmation_and_clears_leases(team):
    shot = create(team)
    timeline = create(team, kind='timeline')
    lease = team['a'].post(url(team, timeline, '/lease'), json={'action': 'acquire', 'assignment_epoch': timeline['assignment_epoch']})
    assert lease.status_code == 200
    before = team['admin'].get(url(team)).json()
    enable(team)
    change_roles(team, team['bid'], ['generator'])
    with pytest.raises(HTTPException) as failure:
        assign(team, team['bid'])
    assert failure.value.status_code == 409
    assert team['admin'].get(url(team)).json() == before
    assign(team, team['bid'], confirm_special=True)
    after = team['admin'].get(url(team)).json()
    assert all(row['assignee_id'] == team['bid'] for row in after)
    assert all(row['assignment_epoch'] == next(r for r in before if r['id']==row['id'])['assignment_epoch'] + 1 for row in after)
    assert all(row['content'] == next(r for r in before if r['id']==row['id'])['content'] for row in after)
    with s.db() as c:
        assert c.execute('SELECT lease_hash FROM collaboration_objects WHERE id=%s', (timeline['id'],)).fetchone()['lease_hash'] is None
        assert br.default_assignee(c, team['production'], 'generator', project_id=team['pid']) == team['bid']
        assert c.execute('SELECT created_by FROM collaboration_objects WHERE id=%s', (shot['id'],)).fetchone()['created_by'] == team['aid']


def test_role_revocation_clears_work_only_for_lost_role(team):
    create(team)
    enable(team)
    change_roles(team, team['aid'], ['writer', 'generator'])
    assign(team, team['aid'], confirm_special=True)
    with actor(team['admin']), s.db() as c:
        br.set_default(c, team['production'], 'writer', team['aid'], br.workflow(c, team['production'])['revision'])
    change_roles(team, team['aid'], ['writer'])
    with s.db() as c:
        assert br.roles(c, team['production'], team['aid']) == {'writer'}
        assert br.default_assignee(c, team['production'], 'writer') == team['aid']
        assert br.default_assignee(c, team['production'], 'generator', project_id=team['pid']) is None
        assert all(row['assignee_id'] is None for row in c.execute('SELECT assignee_id FROM collaboration_objects WHERE project_id=%s', (team['pid'],)))


def test_last_producer_stale_revision_and_wrong_role_are_rejected(team):
    state = enable(team)
    with actor(team['admin']) as uid:
        with pytest.raises(HTTPException), s.db() as c:
            br.set_roles(c, team['production'], uid, [], state['revision'])
    change_roles(team, team['aid'], ['writer'])
    with actor(team['admin']):
        with pytest.raises(HTTPException) as failure, s.db() as c:
            br.set_roles(c, team['production'], team['bid'], ['artist'], state['revision'])
        assert failure.value.status_code == 409
        with pytest.raises(HTTPException), s.db() as c:
            br.assign_episode(c, team['production'], team['pid'], 'generator', team['aid'], br.workflow(c, team['production'])['revision'])
    with actor(team['a']), pytest.raises(HTTPException) as failure, s.db() as c:
        br.set_roles(c, team['production'], team['bid'], ['producer'], br.workflow(c, team['production'])['revision'])
    assert failure.value.status_code == 403


def test_removed_membership_does_not_resolve_stored_roles_or_defaults(team):
    enable(team)
    change_roles(team, team['aid'], ['writer'])
    with s.db() as c:
        c.execute('DELETE FROM production_members WHERE production_id=%s AND user_id=%s', (team['production'], team['aid']))
        assert not br.roles(c, team['production'], team['aid'])
        assert br.default_assignee(c, team['production'], 'writer') is None


def test_transfer_rolls_back_on_history_failure(team, monkeypatch):
    create(team)
    enable(team)
    change_roles(team, team['bid'], ['generator'])
    before = team['admin'].get(url(team)).json()
    calls = []
    original = br._transfer_object
    def fail(c, row, uid):
        original(c, row, uid)
        calls.append(row['id'])
        if len(calls) == 2:
            raise RuntimeError('synthetic transaction failure')
    monkeypatch.setattr(br, '_transfer_object', fail)
    with pytest.raises(RuntimeError):
        assign(team, team['bid'], confirm_special=True)
    assert team['admin'].get(url(team)).json() == before
    with s.db() as c:
        assert c.execute('SELECT 1 FROM episode_staff WHERE project_id=%s', (team['pid'],)).fetchone() is None


def test_actual_http_edits_require_business_role_even_for_existing_assignee(team):
    shot = create(team)
    enable(team)
    change_roles(team, team['aid'], ['writer'])
    assert save(team, shot).status_code == 403
    change_roles(team, team['aid'], ['generator'])
    assert save(team, shot).status_code == 200
    assert save(team, shot, client=team['admin']).status_code == 403


def test_new_shots_inherit_episode_owner_and_other_generator_cannot_create(team):
    enable(team)
    change_roles(team, team['aid'], ['generator'])
    change_roles(team, team['bid'], ['generator'])
    assign(team, team['aid'], confirm_special=True)
    shot = create(team)
    assert shot['assignee_id'] == team['aid']
    response = team['b'].post(url(team), json={'kind':'shot', 'content': {
        'shot': {'id':'forbidden', 'uid':'forbidden', 'description':'not my episode'}, 'nodes':[]}})
    assert response.status_code == 403
    assert all(row['object_key'] != 'forbidden' for row in team['admin'].get(url(team)).json())


def test_workflow_graph_no_longer_has_legacy_all_editors_exception(team):
    enable(team)
    change_roles(team, team['aid'], ['generator'])
    change_roles(team, team['bid'], ['generator'])
    assign(team, team['aid'], confirm_special=True)
    graph = next(row for row in team['a'].get(url(team)).json() if row['kind']=='graph')
    from tests.test_p5_object_transactions import version
    assert team['b'].patch(url(team,graph),json={**version(graph),'content':graph['content']}).status_code==403


def test_producer_cannot_assign_making_objects_to_editor_role(team):
    shot = create(team)
    enable(team)
    change_roles(team, team['bid'], ['editor'])
    from tests.test_p5_object_transactions import version
    response=team['admin'].post(url(team,shot,'/assign'),json={**version(shot),'assignee_id':team['bid']})
    assert response.status_code==403


def test_http_workflow_roles_do_not_need_legacy_editor_or_manager(team):
    base='/api/productions/'+team['production']+'/workflow'
    assert team['a'].get(base).json()['enabled'] is False
    assert team['a'].post(base+'/enable').status_code==403
    state=team['admin'].post(base+'/enable').json()
    assert state['enabled'] and state['can_manage']
    assert state['config']['revision']==1
    viewer_id=team['viewer'].get('/api/auth/status').json()['user']['id']
    response=team['admin'].put(base+'/members/'+viewer_id,json={'revision':1,'roles':['producer','writer']})
    assert response.status_code==200,response.text
    assert team['viewer'].get(base).json()['can_manage']
    with s.db() as c:
        assert c.execute('SELECT role FROM production_members WHERE production_id=%s AND user_id=%s',
                         (team['production'],viewer_id)).fetchone()['role']=='viewer'
    assert team['a'].put(base+'/defaults',json={'revision':2,'role':'writer','user_id':team['aid']}).status_code==403


def test_member_removal_and_rejoin_do_not_revive_roles(team):
    enable(team)
    change_roles(team,team['aid'],['writer','generator'])
    assign(team,team['aid'],confirm_special=True)
    response=team['admin'].delete('/api/productions/'+team['production']+'/members/'+team['aid'])
    assert response.status_code==200,response.text
    with s.db() as c:
        assert not c.execute('SELECT 1 FROM production_business_roles WHERE production_id=%s AND user_id=%s',
                             (team['production'],team['aid'])).fetchone()
    base='/api/productions/'+team['production']+'/workflow'
    state=team['admin'].get(base).json()
    response=team['admin'].put(base+'/members/'+team['aid'],json={'revision':state['config']['revision'],'roles':[]})
    assert response.status_code==200,response.text
    assert team['a'].get(base).json()['my_roles']==[]


def test_source_creation_and_bulk_chapter_assignment_follow_writer_roles(team):
    from tests.test_p5_owned_content import create_chapter,save as save_owned
    enable(team)
    change_roles(team,team['aid'],['writer'])
    chapter=create_chapter(team)
    assert chapter['assignee_id']==team['aid']
    change_roles(team,team['bid'],['artist'])
    response=team['b'].post('/api/productions/'+team['production']+'/sources',json={'title':'no','type':'manual','metadata':{}})
    assert response.status_code==403
    change_roles(team,team['bid'],['writer'])
    second=create_chapter(team)
    assert second['assignee_id'] is None
    with actor(team['admin']),s.db() as c:
        br.assign_business_items(c,team['production'],'chapter',[{k:chapter[k] for k in ('id','revision','assignment_epoch')}],
                                 team['bid'],br.workflow(c,team['production'])['revision'])
    fresh=team['b'].get('/api/productions/'+team['production']+'/owned-content/chapter/'+chapter['id']).json()
    assert save_owned(team,'chapter',fresh,actor=team['b']).status_code==200
    assert save_owned(team,'chapter',fresh,actor=team['a']).status_code==403
    change_roles(team,team['bid'],[])
    with s.db() as c:
        assert c.execute('SELECT assignee_id FROM source_chapters WHERE id=%s',(chapter['id'],)).fetchone()['assignee_id'] is None
        assert c.execute('SELECT count(*) n FROM source_chapter_revisions WHERE chapter_id=%s',(chapter['id'],)).fetchone()['n']>=3


def test_assigning_script_default_does_not_transfer_it_with_generator(team):
    enable(team)
    change_roles(team,team['aid'],['writer'])
    change_roles(team,team['bid'],['generator'])
    with actor(team['admin']),s.db() as c:
        revision=br.workflow(c,team['production'])['revision']
        state=br.assign_episode(c,team['production'],team['pid'],'writer',None,revision)
        script=c.execute('SELECT * FROM episode_scripts WHERE project_id=%s',(team['pid'],)).fetchone()
        assert script['assignee_id']==team['aid']
    assign(team,team['bid'],confirm_special=True)
    with s.db() as c:
        assert c.execute('SELECT * FROM episode_scripts WHERE project_id=%s',(team['pid'],)).fetchone()==script


def test_new_web_project_starts_with_producer_and_unassigned_work(admin):
    response=admin.post('/api/projects',json={'name':'new five role work','creation_mode':'direct','five_role_workflow':True})
    assert response.status_code==200,response.text
    project=response.json()
    assert project['permissions']['business_roles']==['producer']
    assert project['permissions']['can_manage'] and not project['permissions']['can_generate']
    assert all(row['assignee_id'] is None for row in project['objects'])
    with s.db() as c:
        assert c.execute('SELECT assignee_id FROM episode_scripts WHERE project_id=%s',(project['id'],)).fetchone()['assignee_id'] is None


def test_advanced_chapter_transfer_invalidates_stale_business_confirmation(team):
    from tests.test_p5_owned_content import create_chapter,assign as assign_owned
    enable(team)
    change_roles(team,team['aid'],['writer'])
    chapter=create_chapter(team)
    base='/api/productions/'+team['production']+'/workflow'
    state=team['admin'].get(base).json()
    assert state['effective_defaults']['writer']==team['aid']
    assert state['config']['writer_id'] is None
    assign_owned(team,'chapter',chapter,team['aid'])
    response=team['admin'].put(base+'/defaults',json={
        'revision':state['config']['revision'],'role':'writer','user_id':team['aid']})
    assert response.status_code==409,response.text


def test_writer_can_trash_only_owned_chapters_without_manager_role(team):
    from tests.test_p5_owned_content import create_chapter
    enable(team)
    change_roles(team,team['aid'],['writer'])
    chapter=create_chapter(team)
    change_roles(team,team['bid'],['writer'])
    path='/api/productions/'+team['production']+'/chapters/trash'
    payload={'chapter_ids':[chapter['id']],'versions':{chapter['id']:{
        'revision':chapter['revision'],'assignment_epoch':chapter['assignment_epoch']}}}
    assert team['b'].post(path,json=payload).status_code==403
    response=team['a'].post(path,json=payload)
    assert response.status_code==200,response.text


def test_whole_source_cleanup_requires_every_chapter_owner_and_current_versions(team):
    from tests.test_p5_owned_content import create_chapter,assign as assign_owned
    enable(team)
    change_roles(team,team['aid'],['writer'])
    first=create_chapter(team)
    path='/api/productions/'+team['production']+'/sources/'+first['source_id']
    second=team['a'].post(path+'/chapters',json={'title':'第二章','content':'继续'}).json()
    change_roles(team,team['bid'],['writer'])
    second=assign_owned(team,'chapter',second,team['bid'])
    def payload(*chapters):return {'versions':{v['id']:{'revision':v['revision'],'assignment_epoch':v['assignment_epoch']} for v in chapters}}
    response=team['a'].request('DELETE',path,json=payload(first,second))
    assert response.status_code==403,response.text
    assert team['a'].get('/api/productions/'+team['production']+'/chapters').status_code==200
    fresh=assign_owned(team,'chapter',second,team['aid'])
    assert team['a'].request('DELETE',path,json=payload(first,second)).status_code==409
    response=team['a'].request('DELETE',path,json=payload(first,fresh))
    assert response.status_code==200,response.text
    with s.db() as c:
        assert c.execute("SELECT 1 FROM deleted_items WHERE kind='source' AND item_id=%s",(first['source_id'],)).fetchone()
        assert c.execute('SELECT count(*) n FROM source_chapters WHERE source_id=%s',(first['source_id'],)).fetchone()['n']==2


def test_planning_role_aba_cannot_resume_old_provider_handle(team):
    from backend.job_candidates import authorize_resume
    enable(team)
    change_roles(team,team['aid'],['writer'])
    with actor(team['a']),s.db() as c:
        epoch=br.planning_epoch(c,team['production'])
        job={'project_id':team['pid'],'production_id':team['production'],'provider_job_id':'synthetic-handle',
             'collaboration':{'target':{'kind':'adaptation','id':team['production'],'assignment_epoch':epoch}}}
        authorize_resume(c,job)
    change_roles(team,team['aid'],[])
    change_roles(team,team['aid'],['writer'])
    with actor(team['a']),s.db() as c:
        with pytest.raises(HTTPException) as error:authorize_resume(c,job)
        assert error.value.status_code==409
