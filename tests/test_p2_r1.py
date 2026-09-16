from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import database
from backend import store as s
from backend.app import (
    AdaptationSave,
    ChapterCreate,
    EpisodeCreate,
    PromptTemplateSave,
    ScriptSave,
    app,
    cancel,
    create_episode,
    create_source_chapter,
    resume,
    save_adaptation,
    save_episode_script,
    save_prompt_template,
)
from backend.worker import Worker


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client():
    with TestClient(app) as value:
        status = value.get('/api/auth/status').json()
        endpoint = '/api/auth/login' if status['configured'] else '/api/auth/setup'
        response = value.post(endpoint, json={'password': 'integration-test-only'})
        assert response.status_code == 200, response.text
        yield value


def _project(client, name):
    response = client.post('/api/projects', json={'name': name})
    assert response.status_code == 200, response.text
    return response.json()


def _interrupted_job(project_id, suffix):
    job_id = s.uid('job-p2-r1-')
    now = time.time()
    with s.db() as connection:
        connection.execute(
            """INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,phase,created,updated)
            VALUES(%s,%s,%s,%s,'text','interrupted',%s,'interrupted',%s,%s)""",
            (job_id, f'p2-r1-{suffix}-{job_id}', project_id, 'node-p2-r1', s.dumps({'prompt':'frozen'}), now, now),
        )
    return job_id


def _wait_job(job_id, status, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with s.db() as connection:
            row = connection.execute('SELECT status FROM jobs WHERE id=%s', (job_id,)).fetchone()
        if row and row['status'] == status:
            return
        threading.Event().wait(0.03)
    raise AssertionError(f'job {job_id} did not reach {status}')


def test_p2_r1_worker_lock_session_loss_stops_cli_before_claim_and_explicit_restart_claims(client, monkeypatch):
    project = _project(client, 'P2-R1 lock loss')
    environment = {**os.environ, 'PYTHONUTF8':'1'}
    process = subprocess.Popen(
        [sys.executable, '-m', 'backend.worker_cli', '--concurrency', '1'],
        cwd=ROOT, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding='utf-8',
    )
    try:
        started = process.stdout.readline()
        match = re.search(r'lock_backend_pid=(\d+)', started)
        assert match, started
        lock_backend_pid = int(match.group(1))
        with s.db() as connection:
            terminated = connection.execute(
                'SELECT pg_terminate_backend(%s) terminated', (lock_backend_pid,)
            ).fetchone()['terminated']
        assert terminated is True

        job_id = _interrupted_job(project['id'], 'lock-loss')
        with s.db() as connection:
            connection.execute(
                "UPDATE jobs SET status='queued',phase='queued' WHERE id=%s", (job_id,)
            )
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 3, started + stdout + stderr
        with s.db() as connection:
            assert connection.execute(
                'SELECT status FROM jobs WHERE id=%s', (job_id,)
            ).fetchone()['status'] == 'queued'

        claimed = threading.Event()

        def execute(_worker, job):
            assert job['id'] == job_id
            claimed.set()
            return {'restarted': True}

        monkeypatch.setattr(Worker, 'execute', execute)
        replacement = Worker(concurrency=1)
        replacement.start()
        try:
            assert claimed.wait(10)
            _wait_job(job_id, 'succeeded')
            replacement.raise_if_failed()
            print(json.dumps({
                'case':'worker_lock_loss',
                'database':s.init()['database_name'],
                'terminated_backend_pid':lock_backend_pid,
                'cli_returncode':process.returncode,
                'state_before_restart':'queued',
                'state_after_explicit_restart':'succeeded',
                'replacement_lock_backend_pid':replacement.process_lock.backend_pid,
            },sort_keys=True))
        finally:
            replacement.stop()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


def test_p2_r1_first_prompt_write_and_parent_sequences_are_serialized(client):
    with s.db() as connection:
        connection.execute("DELETE FROM settings WHERE key='prompt_library'")
    barrier = threading.Barrier(3)
    outcomes = []
    outcome_lock = threading.Lock()

    def prompt_contender(index):
        barrier.wait()
        try:
            value = save_prompt_template(
                f'first-{index}',
                PromptTemplateSave(revision=0,name=f'first-{index}',kind='text',content='prompt'),
            )
            outcome = ('success', value['revision'])
        except HTTPException as exc:
            outcome = ('conflict', exc.status_code)
        with outcome_lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=prompt_contender,args=(index,)) for index in (1,2)]
    for thread in threads: thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert sorted(outcomes) == [('conflict',409),('success',1)]

    production = client.post('/api/productions',json={'name':'P2-R1 sequences'}).json()
    episode_barrier = threading.Barrier(3)
    episode_results = []

    def episode_contender(index):
        episode_barrier.wait()
        episode_results.append(create_episode(production['id'],EpisodeCreate(title=f'Episode {index}')))

    threads = [threading.Thread(target=episode_contender,args=(index,)) for index in (1,2)]
    for thread in threads: thread.start()
    episode_barrier.wait()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert sorted(item['episode_no'] for item in episode_results) == [1,2]

    source = client.post(
        f'/api/productions/{production["id"]}/sources',
        json={'title':'Source','type':'manual','metadata':{}},
    ).json()
    chapter_barrier = threading.Barrier(3)
    chapter_results = []

    def chapter_contender(index):
        chapter_barrier.wait()
        chapter_results.append(create_source_chapter(
            production['id'],source['id'],ChapterCreate(title=f'Chapter {index}',content='content')
        ))

    threads = [threading.Thread(target=chapter_contender,args=(index,)) for index in (1,2)]
    for thread in threads: thread.start()
    chapter_barrier.wait()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert sorted(item['chapter_no'] for item in chapter_results) == [1,2]
    print(json.dumps({
        'case':'first_write_and_sequences',
        'prompt_outcomes':sorted(outcomes),
        'episode_numbers':sorted(item['episode_no'] for item in episode_results),
        'chapter_numbers':sorted(item['chapter_no'] for item in chapter_results),
    },sort_keys=True))


def test_p2_r1_resume_cancel_races_serialize_and_duplicate_resume_does_not_reset(client, monkeypatch):
    project = _project(client, 'P2-R1 resume cancel')
    original_event = s._event

    def run_race(first, second, expected_status):
        job_id = _interrupted_job(project['id'], expected_status)
        inside = threading.Event()
        release = threading.Event()
        outcomes = []

        def blocked_event(connection, project_id, payload):
            row = connection.execute('SELECT status FROM jobs WHERE id=%s', (job_id,)).fetchone()
            if payload.get('id') == job_id and row and row['status'] == first:
                inside.set()
                assert release.wait(10)
            return original_event(connection, project_id, payload)

        monkeypatch.setattr(s, '_event', blocked_event)

        def invoke(name):
            try:
                value = resume(job_id) if name == 'queued' else cancel(job_id)
                outcomes.append((name, value['status']))
            except HTTPException as exc:
                outcomes.append((name, exc.status_code))

        first_thread = threading.Thread(target=invoke,args=(first,))
        first_thread.start()
        assert inside.wait(10)
        second_thread = threading.Thread(target=invoke,args=(second,))
        second_thread.start()
        release.set()
        for thread in (first_thread,second_thread):
            thread.join(timeout=10)
            assert not thread.is_alive()
        with s.db() as connection:
            status = connection.execute('SELECT status FROM jobs WHERE id=%s',(job_id,)).fetchone()['status']
        assert status == expected_status
        return job_id, outcomes

    _, cancel_first = run_race('cancelled','queued','cancelled')
    assert ('queued',409) in cancel_first
    resumed_job, resume_first = run_race('queued','cancelled','cancelled')
    assert ('queued','queued') in resume_first and ('cancelled','cancelled') in resume_first

    with s.db() as connection:
        connection.execute("UPDATE jobs SET status='interrupted',phase='again' WHERE id=%s",(resumed_job,))
    first = resume(resumed_job)
    assert first['status'] == 'queued'
    with s.db() as connection:
        connection.execute("UPDATE jobs SET status='running',progress=37 WHERE id=%s",(resumed_job,))
    duplicate = resume(resumed_job)
    assert duplicate['status'] == 'running' and duplicate['progress'] == 37
    print(json.dumps({
        'case':'resume_cancel',
        'cancel_first':sorted(cancel_first,key=str),
        'resume_first':sorted(resume_first,key=str),
        'duplicate_resume_state':duplicate['status'],
        'duplicate_resume_progress':duplicate['progress'],
    },sort_keys=True))


def test_p2_r1_event_failure_rolls_back_job_adaptation_and_script(client, monkeypatch):
    project = _project(client, 'P2-R1 transactional events')
    job_id = _interrupted_job(project['id'], 'event-rollback')

    def fail_event(*_args, **_kwargs):
        raise RuntimeError('injected event failure')

    monkeypatch.setattr(s, '_event', fail_event)
    with pytest.raises(RuntimeError, match='injected event failure'):
        s.job_update(job_id,status='cancelled',phase='must rollback')
    with s.db() as connection:
        row = connection.execute('SELECT status,phase FROM jobs WHERE id=%s',(job_id,)).fetchone()
    assert (row['status'],row['phase']) == ('interrupted','interrupted')

    monkeypatch.undo()
    from tests.test_adaptation import setup_production
    production, episode, _chapter, adaptation = setup_production(client,count=1)
    before = client.get(f'/api/productions/{production["id"]}/adaptation').json()
    body = AdaptationSave(**{
        key: adaptation[key] for key in ('revision','adaptationPlan','episodePlans','monetizationPlan')
    })
    monkeypatch.setattr(s, 'event', fail_event)
    with pytest.raises(RuntimeError, match='injected event failure'):
        save_adaptation(production['id'],body)
    after = client.get(f'/api/productions/{production["id"]}/adaptation').json()
    assert after == before

    monkeypatch.undo()
    saved_adaptation = save_adaptation(production['id'],body)
    script = client.get(f'/api/productions/{production["id"]}/episode-scripts/1').json()
    assert script['revision'] >= 1 and saved_adaptation['revision'] > body.revision
    script_body = ScriptSave(**{
        **{key:script[key] for key in (
            'revision','title','synopsis','body','estimatedDuration','sourceChapterRefs',
            'storyGoal','paywallBeat','characters','scenes','props',
        )},
        'body':'must roll back',
    })
    monkeypatch.setattr(s, 'event', fail_event)
    with s.db() as connection:
        history_before = connection.execute(
            'SELECT COUNT(*) count FROM episode_script_revisions WHERE project_id=%s',(episode['id'],)
        ).fetchone()['count']
    with pytest.raises(RuntimeError, match='injected event failure'):
        save_episode_script(production['id'],1,script_body)
    with s.db() as connection:
        saved = connection.execute(
            'SELECT revision,body FROM episode_scripts WHERE project_id=%s',(episode['id'],)
        ).fetchone()
        history_after = connection.execute(
            'SELECT COUNT(*) count FROM episode_script_revisions WHERE project_id=%s',(episode['id'],)
        ).fetchone()['count']
    assert saved['revision'] == script['revision'] and saved['body'] == script['body']
    assert history_after == history_before
    print(json.dumps({
        'case':'transactional_events',
        'job_state_after_event_failure':row['status'],
        'adaptation_rolled_back':after == before,
        'script_revision_after_event_failure':saved['revision'],
        'script_history_before':history_before,
        'script_history_after':history_after,
    },sort_keys=True))


def _wait_for_advisory_wait(backend_pid, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with s.db() as observer:
            row = observer.execute(
                'SELECT wait_event_type,wait_event FROM pg_stat_activity WHERE pid=%s',(backend_pid,)
            ).fetchone()
        if row and row['wait_event_type'] == 'Lock' and row['wait_event'] == 'advisory':
            return
        threading.Event().wait(0.02)
    raise AssertionError(f'backend {backend_pid} did not block on the event publication lock')


def test_p2_r1_sse_event_ids_follow_commit_order_and_rollback_gaps_reconnect_safely(monkeypatch):
    monkeypatch.setattr(s,'EVENT_RETENTION',3)
    with s.db() as connection:
        connection.execute('DELETE FROM events')

    first = database.connect()
    second = database.connect()
    entered = threading.Event()
    finished = threading.Event()
    try:
        s._event(first,'cursor-project',{'type':'project','revision':1})
        second_pid = second.execute('SELECT pg_backend_pid() pid').fetchone()['pid']

        def publish_second():
            entered.set()
            s._event(second,'cursor-project',{'type':'project','revision':2})
            second.commit()
            finished.set()

        thread = threading.Thread(target=publish_second)
        thread.start()
        assert entered.wait(10)
        _wait_for_advisory_wait(second_pid)
        assert not finished.is_set()
        first.commit()
        assert finished.wait(10)
        thread.join(timeout=10)
        assert not thread.is_alive()
        with s.db() as connection:
            committed = connection.execute(
                "SELECT id,payload FROM events WHERE project_id='cursor-project' ORDER BY id"
            ).fetchall()
        assert [json.loads(row['payload'])['revision'] for row in committed] == [1,2]
        assert committed[0]['id'] < committed[1]['id']
    finally:
        first.close()
        second.close()

    rollback = database.connect()
    after_gap = database.connect()
    gap_finished = threading.Event()
    try:
        s._event(rollback,'cursor-project',{'type':'project','revision':3})
        gap_pid = after_gap.execute('SELECT pg_backend_pid() pid').fetchone()['pid']

        def publish_after_gap():
            s._event(after_gap,'cursor-project',{'type':'project','revision':4})
            after_gap.commit()
            gap_finished.set()

        thread = threading.Thread(target=publish_after_gap)
        thread.start()
        _wait_for_advisory_wait(gap_pid)
        rollback.rollback()
        assert gap_finished.wait(10)
        thread.join(timeout=10)
        with s.db() as connection:
            rows = connection.execute(
                "SELECT id,payload FROM events WHERE project_id='cursor-project' ORDER BY id"
            ).fetchall()
        revisions = [json.loads(row['payload'])['revision'] for row in rows]
        assert revisions == [1,2,4]
        from backend.app import _event_cursor
        last_seen = rows[1]['id']
        latest = rows[-1]['id']
        assert _event_cursor(
            latest,last_event_id=str(last_seen),oldest_retained=rows[0]['id'],
            requested_retained=True,visible_backlog=1,
        ) == last_seen
        assert [json.loads(row['payload'])['revision'] for row in rows if row['id'] > last_seen] == [4]

        s.event('cursor-project',{'type':'project','revision':5})
        with s.db() as connection:
            retained = connection.execute(
                "SELECT payload FROM events WHERE project_id='cursor-project' ORDER BY id"
            ).fetchall()
        assert [json.loads(row['payload'])['revision'] for row in retained] == [2,4,5]
        print(json.dumps({
            'case':'sse_commit_cursor',
            'committed_ids':[row['id'] for row in committed],
            'rollback_gap_visible_ids':[row['id'] for row in rows],
            'rollback_gap_revisions':revisions,
            'reconnect_cursor':last_seen,
            'latest_id':latest,
            'retained_revisions':[json.loads(row['payload'])['revision'] for row in retained],
        },sort_keys=True))
    finally:
        rollback.close()
        after_gap.close()
