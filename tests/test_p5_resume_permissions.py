"""Resuming a durable job is not a project-editor bypass around object ACLs."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import uuid
import pytest
from backend import store as s
from tests.test_p5_object_transactions import team,admin,clients,clear_auth_rate_limits,url,version,save
from tests.test_p5_canonical_integration import node
from tests.test_p5_object_candidates import submit
from tests.test_p5_relation_candidates import extraction
from tests.test_p5_owned_content import create_chapter,save as save_owned
from tests.platform_model_helpers import publish_test_model
from tests.test_p3_r2_interleavings import wait_for_db_waiters


def interrupted(team):
    row=node(team,team['a'],'resume-node');model=uuid.uuid4().hex
    publish_test_model(team['admin'],model)
    response=submit(team,row,model);assert response.status_code==200,response.text
    job=response.json()
    assert s.job_update(job['id'],status='interrupted',error='synthetic interruption')
    return row,job


def path(job):return '/api/jobs/'+job['id']+'/resume'


def test_only_current_owner_can_requeue_unchanged_job(team):
    row,job=interrupted(team)
    for actor in (team['b'],team['admin'],team['viewer']):
        response=actor.post(path(job));assert response.status_code==403,response.text
        assert team['a'].get('/api/jobs/'+job['id']).json()['status']=='interrupted'
    response=team['a'].post(path(job));assert response.status_code==200,response.text
    resumed=response.json()
    assert resumed['status']=='queued' and resumed['input']==job['input']
    assert resumed['collaboration']==job['collaboration']


@pytest.mark.parametrize('change',['content','aba'])
def test_old_snapshot_cannot_be_requeued_after_edit_or_assignment_aba(team,change):
    row,job=interrupted(team)
    if change=='content':
        value=deepcopy(row['content']);value['node']['data']['text']='new human content'
        assert save(team,row,value).status_code==200
    else:
        for uid in (team['bid'],team['aid']):
            response=team['admin'].post(url(team,row,'/assign'),json={**version(row),'assignee_id':uid})
            assert response.status_code==200,response.text
            row=response.json()
    before=team['a'].get('/api/jobs/'+job['id']).json()
    response=team['a'].post(path(job));assert response.status_code==409,response.text
    assert team['a'].get('/api/jobs/'+job['id']).json()==before


def test_relational_retry_requires_current_chapter_owner_and_original_revision(team):
    row=create_chapter(team);model=uuid.uuid4().hex;publish_test_model(team['admin'],model)
    response=extraction(team,[row],model);assert response.status_code==200,response.text
    job=response.json()['jobs'][0];assert s.job_update(job['id'],status='interrupted')
    assert team['admin'].post(path(job)).status_code==403
    changed=save_owned(team,'chapter',row,content='new source');assert changed.status_code==200,changed.text
    response=team['a'].post(path(job));assert response.status_code==409,response.text
    assert team['a'].get('/api/jobs/'+job['id']).json()['status']=='interrupted'


def test_resume_rechecks_after_real_pg_object_lock_wait(team):
    row,job=interrupted(team)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with s.db() as c:
            c.execute('SELECT id FROM collaboration_objects WHERE id=%s FOR UPDATE',(row['id'],))
            running=pool.submit(team['a'].post,path(job))
            waits=wait_for_db_waiters(1);assert all(item['blockers'] for item in waits)
            print('P5 resume object wait:',waits)
            value=deepcopy(row['content']);value['node']['data']['text']='changed while retry waits'
            # The blocker commits only a fixture content/revision change; user
            # identities and authorization are still created through public APIs.
            c.execute('UPDATE collaboration_objects SET content=%s,revision=revision+1 WHERE id=%s',
                      (s.dumps(value),row['id']))
        response=running.result(15)
    assert response.status_code==409,response.text
    assert team['a'].get('/api/jobs/'+job['id']).json()['status']=='interrupted'


def test_remote_resume_keeps_original_handle_and_allows_edits_but_not_reassignment(team):
    model=uuid.uuid4().hex
    publish_test_model(team['admin'],model,kind='video',provider_type='minimax',upstream_model='MiniMax-Hailuo-2.3')
    response=team['a'].post(url(team),json={'kind':'node','content':{'node':{
        'id':'remote-video','type':'media','data':{'kind':'video','prompt':'saved prompt'}}}})
    assert response.status_code==201,response.text
    row=response.json();response=submit(team,row,model,kind='video')
    assert response.status_code==200,response.text
    job=response.json();assert s.job_update(job['id'],status='interrupted',provider_job_id='synthetic-existing-handle')
    value=deepcopy(row['content']);value['node']['data']['prompt']='human v2'
    response=save(team,row,value);assert response.status_code==200,response.text
    row=response.json()
    assert team['admin'].post(path(job)).status_code==403
    response=team['a'].post(path(job));assert response.status_code==200,response.text
    assert response.json()['provider_job_id']=='synthetic-existing-handle'
    assert response.json()['input']==job['input']
    assert response.json()['collaboration']==job['collaboration']
    assert s.job_update(job['id'],status='interrupted')
    response=team['admin'].post(url(team,row,'/assign'),json={**version(row),'assignee_id':team['bid']})
    assert response.status_code==200,response.text
    row=response.json()
    assert team['a'].post(path(job)).status_code==403
    # P3 also restricts another ordinary editor from resuming the submitter's
    # job. Preserve that guard; do not weaken it to reach the P5 epoch check.
    assert team['b'].post(path(job)).status_code==403
    response=team['admin'].post(url(team,row,'/assign'),json={**version(row),'assignee_id':team['aid']})
    assert response.status_code==200,response.text
    response=team['a'].post(path(job));assert response.status_code==409,response.text
    assert team['b'].get('/api/jobs/'+job['id']).json()['status']=='interrupted'
