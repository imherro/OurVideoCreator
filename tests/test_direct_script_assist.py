import uuid
import json
import pytest
from backend import store as s
from tests.test_direct_script_manual import admin, clients, clear_auth_rate_limits, checked, endpoint, save
from tests.test_p5_relation_candidates import complete_without_network, SCRIPT, expected
from tests.platform_model_helpers import publish_test_model
from tests.test_p5_object_transactions import team
from tests.test_p5_owned_content import assign
from tests.test_p5_owned_content import create_chapter
from concurrent.futures import ThreadPoolExecutor


def setup_assist(admin):
    project=checked(admin.post('/api/projects',json={'name':'Direct assist','creation_mode':'direct'}))
    row=checked(admin.get(endpoint(project)))
    row=checked(save(admin,project,row,body='Human original'))
    model='direct-'+uuid.uuid4().hex
    publish_test_model(admin,model)
    payload={'revision':row['revision'],'assignment_epoch':row['assignment_epoch'],
             'model_id':model,'instruction':'写本集，保留人物关系','submission_id':uuid.uuid4().hex}
    return project,row,payload


def test_direct_assist_no_plan_dedup_candidate_and_explicit_adoption(admin,monkeypatch):
    project,row,payload=setup_assist(admin)
    path=endpoint(project)+'/assist'
    job=checked(admin.post(path,json=payload))
    assert job['input']['schema_version']=='direct-episode-script/v1'
    assert 'Human original' in job['input']['prompt']
    assert admin.get(endpoint(project)).json()==row
    assert checked(admin.post(path,json=payload))['id']==job['id']
    assert admin.post(path,json={**payload,'submission_id':uuid.uuid4().hex}).status_code==409
    complete_without_network(monkeypatch,job,SCRIPT)
    assert admin.get(endpoint(project)).json()==row
    adopted=checked(admin.post(f"/api/projects/{project['id']}/candidates/{job['id']}/adopt",json=expected(row)))
    assert adopted['target']['body']==SCRIPT['body']
    assert adopted['target']['status']=='draft'
    assert adopted['target']['metadata']['origin']=='direct_ai'
    assert adopted['target']['metadata']['adaptationLinked'] is False


@pytest.mark.parametrize('change',['current','previous','video'])
def test_changed_inputs_reject_even_explicit_stale_override(admin,monkeypatch,change):
    project,row,payload=setup_assist(admin)
    if change=='previous':
        previous=project
        project=checked(admin.post('/api/productions/'+project['production_id']+'/episodes',json={}))
        row=checked(admin.get(endpoint(project)))
        payload.update(revision=row['revision'],assignment_epoch=row['assignment_epoch'])
    job=checked(admin.post(endpoint(project)+'/assist',json=payload))
    complete_without_network(monkeypatch,job,SCRIPT)
    if change=='current':
        row=checked(save(admin,project,row,body='Human newer edit'))
    elif change=='previous':
        previous_row=checked(admin.get(endpoint(previous)))
        checked(save(admin,previous,previous_row,body='Previous episode changed'))
    else:
        # Isolated canonical node, not an unattached generated candidate asset.
        from tests.test_p5_object_transactions import create
        node=create({'pid':project['id'],'a':admin},kind='node',node={'id':'accepted-video','type':'video',
               'data':{'kind':'video'}})
        with s.db() as c:
            content=node['content'];content['node']['data']['assetId']='fixture-adopted-video'
            c.execute('UPDATE collaboration_objects SET content=%s WHERE id=%s',(json.dumps(content),node['id']))
    response=admin.post(f"/api/projects/{project['id']}/candidates/{job['id']}/adopt",json=expected(row,accept_stale=True))
    assert response.status_code==409,response.text
    assert admin.get(endpoint(project)).json()==row


def test_direct_assist_rejects_private_parameters_and_stale_revision(admin):
    project,row,payload=setup_assist(admin)
    path=endpoint(project)+'/assist'
    assert admin.post(path,json={**payload,'api_key':'not-a-real-key'}).status_code==422
    assert admin.post(path,json={**payload,'instruction':'   '}).status_code==400
    checked(save(admin,project,row,body='Newer body'))
    assert admin.post(path,json=payload).status_code==409
    assert admin.get('/api/projects/'+project['id']+'/jobs').json()==[]


def test_direct_assist_requires_current_owner_even_without_plan(team):
    project=checked(team['admin'].get('/api/projects/'+team['pid']))
    row=checked(team['a'].get(endpoint(project)))
    row=assign(team,'script',row,team['aid'])
    model='owner-'+uuid.uuid4().hex;publish_test_model(team['admin'],model)
    payload={'revision':row['revision'],'assignment_epoch':row['assignment_epoch'],'model_id':model,
             'instruction':'Write only this episode','submission_id':uuid.uuid4().hex}
    for actor in ('b','viewer','admin'):
        response=team[actor].post(endpoint(project)+'/assist',json=payload)
        assert response.status_code==403,response.text
    job=checked(team['a'].post(endpoint(project)+'/assist',json=payload))
    assert job['collaboration']['target']['assignment_epoch']==row['assignment_epoch']
    assign(team,'script',row,team['bid'])
    assert team['a'].post(endpoint(project)+'/assist',json=payload).status_code==403


def test_generic_endpoint_rebuilds_direct_prompt_and_rejects_changed_context(admin):
    project,row,payload=setup_assist(admin)
    job=checked(admin.post(endpoint(project)+'/assist',json=payload))
    s.job_update(job['id'],status='failed',error='test-only terminal state')
    fake={**job['input'],'prompt':'FORGED PROMPT','system_prompt':'FORGED SYSTEM'}
    response=checked(admin.post('/api/projects/'+project['id']+'/jobs',json={
        'kind':'text','node_id':job['node_id'],'submission_id':uuid.uuid4().hex,'input':fake}))
    assert 'FORGED' not in response['input']['prompt']
    assert 'FORGED' not in response['input']['system_prompt']
    assert response['input']['schema_version']=='direct-episode-script/v1'
    s.job_update(response['id'],status='failed',error='test-only terminal state')
    fake['episode_script_generation']={**fake['episode_script_generation'],'contextFingerprint':'wrong'}
    assert admin.post('/api/projects/'+project['id']+'/jobs',json={
        'kind':'text','node_id':job['node_id'],'submission_id':uuid.uuid4().hex,'input':fake}).status_code==409


def test_busy_previous_script_rejects_adoption_without_deadlock(admin,monkeypatch):
    first,first_row,payload=setup_assist(admin)
    project=checked(admin.post('/api/productions/'+first['production_id']+'/episodes',json={}))
    row=checked(admin.get(endpoint(project)))
    payload.update(revision=row['revision'],assignment_epoch=row['assignment_epoch'])
    job=checked(admin.post(endpoint(project)+'/assist',json=payload))
    complete_without_network(monkeypatch,job,SCRIPT)
    with s.db() as c:
        c.execute('SELECT project_id FROM episode_scripts WHERE project_id=%s FOR UPDATE',(first['id'],)).fetchone()
        response=admin.post(f"/api/projects/{project['id']}/candidates/{job['id']}/adopt",json=expected(row))
        assert response.status_code==409,response.text
    assert admin.get(endpoint(project)).json()==row
    assert admin.post(f"/api/projects/{project['id']}/candidates/{job['id']}/adopt",json=expected(row)).status_code==200


def test_two_simultaneous_submissions_create_only_one_job(admin):
    project,row,payload=setup_assist(admin)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda identifier:admin.post(endpoint(project)+'/assist',
            json={**payload,'submission_id':identifier}),[uuid.uuid4().hex,uuid.uuid4().hex]))
    assert sorted(response.status_code for response in responses)==[200,409]
    assert len(admin.get('/api/projects/'+project['id']+'/jobs').json())==1


def test_direct_draft_explicit_chapter_revision_is_a_dependency(team,monkeypatch):
    chapter=create_chapter(team)
    project=checked(team['admin'].post('/api/productions/'+team['production']+'/episodes',json={'creation_mode':'direct'}))
    row=checked(team['admin'].get(endpoint(project)))
    row=assign(team,'script',row,team['aid'])
    row=checked(save(team['a'],project,row,body='Direct with explicit source',sourceChapterRefs=[chapter['id']]))
    model='source-'+uuid.uuid4().hex;publish_test_model(team['admin'],model)
    job=checked(team['a'].post(endpoint(project)+'/assist',json={'revision':row['revision'],
        'assignment_epoch':row['assignment_epoch'],'model_id':model,'instruction':'Extend this scene','submission_id':uuid.uuid4().hex}))
    complete_without_network(monkeypatch,job,SCRIPT)
    checked(team['a'].put('/api/productions/'+team['production']+'/chapters/'+chapter['id'],json={
        'title':chapter['title'],'content':'Changed draft source','revision':chapter['revision'],
        'assignment_epoch':chapter['assignment_epoch']}))
    # Draft scripts are not marked stale by source edits; dependency still blocks.
    assert team['a'].get(endpoint(project)).json()['revision']==row['revision']
    response=team['a'].post(f"/api/projects/{project['id']}/candidates/{job['id']}/adopt",json=expected(row,accept_stale=True))
    assert response.status_code==409,response.text
