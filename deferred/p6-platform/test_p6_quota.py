"""Atomic submission-unit reservations, exercised on real PostgreSQL."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import threading
import uuid

import pytest
from backend import job_admission,job_execution,job_quota,store as s
from tests.test_p5_object_transactions import team,admin,clients,clear_auth_rate_limits,save
from tests.test_p5_canonical_integration import node
from tests.test_p5_object_candidates import submit
from tests.platform_model_helpers import publish_test_model


@contextmanager
def limits(**changes):
    with s.db() as c:
        previous=job_quota.settings(c)
        job_quota.configure(c,previous['revision'],changes)
    try:yield
    finally:
        with s.db() as c:
            job_quota.configure(c,job_quota.settings(c)['revision'],previous['settings'])


def daily(text):
    return {**job_quota.DEFAULTS['daily_user'],'text':text}


def model_for(team):
    model=uuid.uuid4().hex;publish_test_model(team['admin'],model)
    return model


def test_one_remaining_unit_concurrent_admissions_cannot_oversell(team):
    rows=[node(team,team['a'],f'p6-limit-{i}') for i in range(2)]
    model=model_for(team);barrier=threading.Barrier(2)
    def contender(row):
        barrier.wait(timeout=10)
        return submit(team,row,model)
    with limits(daily_user=daily(1)),ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(contender,rows))
    assert sorted(r.status_code for r in results)==[200,429],[r.text for r in results]
    winner=next(r.json() for r in results if r.status_code==200)
    with s.db() as c:
        counts=c.execute('''SELECT COUNT(*) n,SUM(u.units) units FROM job_step_usage u
            JOIN job_reservations r ON r.job_id=u.job_id WHERE r.actor_user_id=%s''',
            (winner['actor_user_id'],)).fetchone()
    assert counts=={'n':1,'units':1}


def test_replay_at_full_quota_does_not_reserve_twice(team):
    row=node(team,team['a'],'p6-repeat-limit');model=model_for(team);key=uuid.uuid4().hex
    with limits(daily_user=daily(1)):
        first=submit(team,row,model,submission_id=key)
        replay=submit(team,row,model,submission_id=key)
        other=submit(team,row,model)
    assert first.status_code==200 and replay.status_code==200
    assert first.json()['id']==replay.json()['id']
    assert other.status_code==429,other.text


def test_batch_quota_failure_rolls_back_jobs_bindings_plans_and_events(team):
    model=model_for(team);group=uuid.uuid4().hex
    for i in range(2):
        row=node(team,team['a'],f'p6-batch-{i}')
        content=deepcopy(row['content']);content['node']['data'].update(model_id=model,prompt='batch text')
        assert save(team,row,content).status_code==200
    with s.db() as c:
        before=c.execute('SELECT COUNT(*) n FROM events WHERE project_id=%s',(team['pid'],)).fetchone()['n']
    with limits(daily_user=daily(1)):
        response=team['a'].post('/api/projects/'+team['pid']+'/run',json={
            'submission_id':group,'node_ids':['p6-batch-0','p6-batch-1'],'exact':True})
    assert response.status_code==429,response.text
    with s.db() as c:
        for table in ('jobs','job_private','job_reservations','job_steps','job_step_usage'):
            if table=='jobs':
                count=c.execute('SELECT COUNT(*) n FROM jobs WHERE project_id=%s',(team['pid'],)).fetchone()['n']
            else:
                count=c.execute(f'SELECT COUNT(*) n FROM {table} x JOIN jobs j ON j.id=x.job_id WHERE j.project_id=%s',
                                (team['pid'],)).fetchone()['n']
            assert count==0,table
        assert c.execute('SELECT COUNT(*) n FROM events WHERE project_id=%s',(team['pid'],)).fetchone()['n']==before


@pytest.mark.parametrize('sent',[False,True])
def test_cancel_only_releases_proven_unsent_units(team,sent):
    row=node(team,team['a'],'p6-cancel-limit');model=model_for(team)
    with limits(daily_user=daily(1)):
        response=submit(team,row,model);assert response.status_code==200,response.text
        jid=response.json()['id']
        if sent:
            with s.db() as c:job=job_execution.claim(c,jid,'quota-test')
            with job_execution.scope(job),s.db() as c:
                assert job_execution.begin_step(c,jid,'generate',{'prompt':'frozen test'}) is None
        cancelled=team['a'].post('/api/jobs/'+jid+'/cancel')
        assert cancelled.status_code==200,cancelled.text
        next_job=submit(team,row,model)
        assert next_job.status_code==(429 if sent else 200),next_job.text
    with s.db() as c:
        usage=c.execute('SELECT state,remote_open FROM job_step_usage WHERE job_id=%s',(jid,)).fetchone()
    assert usage=={'state':'submitted' if sent else 'released','remote_open':sent}


def test_queue_pause_and_provider_pause_are_admission_guards(team):
    row=node(team,team['a'],'p6-pause');model=model_for(team)
    with s.db() as c:
        provider=c.execute('SELECT provider_id FROM model_catalog WHERE id=%s',(model,)).fetchone()['provider_id']
    for changed in ({'paused':True},{'paused_providers':[provider]},{'queue_user':0},{'queue_team':0}):
        with limits(**changed):
            response=submit(team,row,model)
            assert response.status_code==429,response.text
    assert submit(team,row,model).status_code==200


def test_planned_work_counts_two_passes_and_image_units_not_http_calls():
    assert job_quota.initial_plan('storyboard',{'film_bible':True},{'type':'openai'})==[
        {'name':'visual_bible','kind':'text','units':1},{'name':'bound_storyboard','kind':'text','units':1}]
    assert job_quota.initial_plan('image',{}, {'type':'openai','job_parameters':{'n':3}})==[
        {'name':'generate','kind':'image','units':3}]
    assert job_quota.initial_plan('image',{}, {'type':'volcengine_ark','job_parameters':{}})[0]['units']==1


def test_quota_day_and_queue_deadline_remain_bound_to_admission(team,monkeypatch):
    row=node(team,team['a'],'p6-day');model=model_for(team)
    monkeypatch.setattr(job_execution,'now',lambda c:1789603190.0)
    response=submit(team,row,model);assert response.status_code==200,response.text
    jid=response.json()['id']
    with s.db() as c:before=c.execute('SELECT * FROM job_reservations WHERE job_id=%s',(jid,)).fetchone()
    monkeypatch.setattr(job_execution,'now',lambda c:1789689590.0)
    replay=submit(team,row,model,submission_id=response.json()['submission_id'])
    assert replay.status_code==200,replay.text
    with s.db() as c:after=c.execute('SELECT * FROM job_reservations WHERE job_id=%s',(jid,)).fetchone()
    assert before==after
    assert before['queue_expires_at']-before['admitted_at']==86400
