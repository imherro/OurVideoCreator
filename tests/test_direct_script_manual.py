"""Manual direct scripts retain the existing owned canonical table and review gate."""
import uuid
from backend import store as s
from backend.adaptation import SCRIPT_FIELDS, _stale_scripts
from tests.test_p5_object_transactions import team, admin, clients, clear_auth_rate_limits
from tests.test_p5_owned_content import assign, create_chapter


def checked(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def endpoint(project):
    return f"/api/productions/{project['production_id']}/episode-scripts/{project['episode_no']}"


def save(client, project, row, **patch):
    payload={key:row[key] for key in SCRIPT_FIELDS}
    return client.put(endpoint(project), json={**payload,**patch,'revision':row['revision'],'assignment_epoch':row['assignment_epoch']})


def approve(client, project, row):
    row=checked(client.post(endpoint(project)+'/review',json={'revision':row['revision'],'assignment_epoch':row['assignment_epoch']}))
    return checked(client.post(endpoint(project)+'/approve',json={'revision':row['revision'],'assignment_epoch':row['assignment_epoch']}))


def test_direct_new_project_and_unplanned_episode_have_one_reviewed_script(admin):
    first=checked(admin.post('/api/projects',json={'name':'Direct manual','creation_mode':'direct','duration':45,'ratio':'9:16'}))
    assert first['document']['creationMode']=='direct'
    second=checked(admin.post('/api/productions/'+first['production_id']+'/episodes',json={'title':'No plan needed'}))
    assert second['document']['creationMode']=='direct'
    assert second['document']['duration']==45 and second['document']['ratio']=='9:16'
    listing=checked(admin.get('/api/productions/'+first['production_id']+'/scripts'))
    assert {row['episodeNo'] for row in listing}=={1,2}
    assert next(row for row in listing if row['episodeNo']==2)['plan'] is None
    for project in (first,second):
        initial=checked(admin.get(endpoint(project)))
        row=checked(save(admin,project,initial,body='场景一：两人在车站相遇。',title='手写正文'))
        assert row['status']=='draft' and row['metadata']['adaptationLinked'] is False
        assert admin.post(endpoint(project)+'/approve',json={'revision':row['revision'],'assignment_epoch':row['assignment_epoch']}).status_code==400
        saved=approve(admin,project,row)
        assert saved['status']=='approved'
        current=checked(admin.get('/api/projects/'+project['id']))
        scripts=[node for node in current['document']['nodes'] if node['id']==saved['metadata']['projectionNodeId']]
        assert len(scripts)==1 and '两人在车站' in str(scripts[0]['data'])
        assert admin.get('/api/projects/'+project['id']+'/jobs').json()==[]
        assert save(admin,project,initial,body='late').status_code==409


def test_direct_script_ownership_review_and_source_dependencies(team):
    project=checked(team['admin'].post('/api/productions/'+team['production']+'/episodes',json={'creation_mode':'direct'}))
    row=checked(team['a'].get(endpoint(project)))
    row=assign(team,'script',row,team['aid'])
    row=checked(save(team['a'],project,row,body='Manual script'))
    assert save(team['b'],project,row,body='unauthorized').status_code==403
    assert save(team['viewer'],project,row,body='unauthorized').status_code==403
    review=checked(team['a'].post(endpoint(project)+'/review',json={'revision':row['revision'],'assignment_epoch':row['assignment_epoch']}))
    assert team['a'].post(endpoint(project)+'/approve',json={'revision':review['revision'],'assignment_epoch':review['assignment_epoch']}).status_code==403
    row=checked(team['admin'].post(endpoint(project)+'/approve',json={'revision':review['revision'],'assignment_epoch':review['assignment_epoch']}))
    with s.db() as connection:
        _stale_scripts(connection,team['production'])
    assert team['a'].get(endpoint(project)).json()==row
    chapter=create_chapter(team)
    row=checked(save(team['a'],project,row,sourceChapterRefs=[chapter['id']]))
    review=checked(team['a'].post(endpoint(project)+'/review',json={'revision':row['revision'],'assignment_epoch':row['assignment_epoch']}))
    checked(team['admin'].post(endpoint(project)+'/approve',json={'revision':review['revision'],'assignment_epoch':review['assignment_epoch']}))
    checked(team['a'].put('/api/productions/'+team['production']+'/chapters/'+chapter['id'],json={
        'title':chapter['title'],'content':'Changed explicit source','revision':chapter['revision'],'assignment_epoch':chapter['assignment_epoch']}))
    assert team['a'].get(endpoint(project)).json()['status']=='stale'


def test_legacy_creation_does_not_skip_adaptation_review(admin):
    project=checked(admin.post('/api/projects',json={'name':'Legacy adaptation'}))
    assert project['document'].get('creationMode','adaptation')=='adaptation'
    row=checked(admin.get(endpoint(project)))
    row=checked(save(admin,project,row,body='Legacy planned script'))
    row=checked(admin.post(endpoint(project)+'/review',json={'revision':row['revision'],'assignment_epoch':row['assignment_epoch']}))
    assert admin.post(endpoint(project)+'/approve',json={'revision':row['revision'],'assignment_epoch':row['assignment_epoch']}).status_code==400
    assert admin.post('/api/projects',json={'creation_mode':'invalid'}).status_code in (400,422)
    assert admin.post('/api/productions/'+project['production_id']+'/episodes',json={'creation_mode':''}).status_code==400


def test_direct_episode_can_explicitly_adopt_an_adaptation_candidate_and_restore_dependencies(admin,monkeypatch):
    from tests.test_p5_relation_candidates import approved_plan, complete_without_network, SCRIPT
    from tests.platform_model_helpers import publish_test_model
    project=checked(admin.post('/api/projects',json={'name':'Switch creative source','creation_mode':'direct'}))
    local={'admin':admin,'a':admin,'pid':project['id'],'production':project['production_id']}
    chapter=create_chapter(local);approved_plan(local,chapter)
    before=checked(admin.get(endpoint(project)))
    model='manual-transition-'+uuid.uuid4().hex;publish_test_model(admin,model)
    jobs=checked(admin.post('/api/productions/'+project['production_id']+'/script-generations',json={
        'episode_nos':[1],'model_id':model,'submission_id':uuid.uuid4().hex}))
    job=jobs['jobs'][0];complete_without_network(monkeypatch,job,SCRIPT)
    assert admin.get(endpoint(project)).json()==before
    adopted=checked(admin.post('/api/projects/'+project['id']+'/candidates/'+job['id']+'/adopt',json={
        'expected_revision':before['revision'],'assignment_epoch':before['assignment_epoch']}))['target']
    assert adopted['metadata']['adaptationLinked'] is True and adopted['metadata']['origin']=='adaptation'
    row=approve(admin,project,adopted)
    with s.db() as connection:_stale_scripts(connection,project['production_id'])
    assert admin.get(endpoint(project)).json()['status']=='stale'
