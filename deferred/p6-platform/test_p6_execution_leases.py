"""DEFERRED old P6 platform experiments; not P6-SINGLE-01 acceptance.

Preserved source: runtime attempt integration is intentionally disconnected.
Independent handle/resource behavior is covered by active SINGLE tests.
"""
import threading
import time

import pytest
from fastapi.testclient import TestClient

from backend import store as s
from backend import job_execution as execution
from backend.app import app
from tests.auth_helpers import login_admin


@pytest.fixture
def job_id():
    with TestClient(app) as client:
        login_admin(client)
        response = client.post('/api/projects', json={'name': 'P6 lease fixture'})
        assert response.status_code == 200, response.text
        pid = response.json()['id']
    jid = s.uid('job-')
    with s.db() as c:
        c.execute('''INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated,execution_phase)
            VALUES(%s,%s,%s,'fixture','text','queued','{}',%s,%s,'queued')''',
            (jid, s.uid('submission-'), pid, time.time(), time.time()))
    return jid


def claim(jid, worker='worker-a'):
    with s.db() as c:
        return execution.claim(c, jid, worker)


def expire(jid, phase=None):
    with s.db() as c:
        c.execute('UPDATE jobs SET lease_expires_at=EXTRACT(EPOCH FROM clock_timestamp())-1 WHERE id=%s', (jid,))
        if phase:
            c.execute('UPDATE jobs SET execution_phase=%s WHERE id=%s', (phase, jid))


def test_two_pg_claims_only_one_current_attempt(job_id):
    barrier = threading.Barrier(2)
    results, errors = [], []
    def contender(worker):
        try:
            barrier.wait(timeout=10)
            results.append(claim(job_id, worker))
        except BaseException as error:
            errors.append(error)
    threads = [threading.Thread(target=contender, args=(f'worker-{i}',)) for i in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=15)
    assert not any(thread.is_alive() for thread in threads)
    assert not errors
    assert sum(result is not None for result in results) == 1
    with s.db() as c:
        assert c.execute('SELECT COUNT(*) AS n FROM job_attempts WHERE job_id=%s', (job_id,)).fetchone()['n'] == 1


def test_live_lease_not_reclaimed_and_heartbeat_records_db_clock(job_id):
    first = claim(job_id)
    assert claim(job_id, 'worker-b') is None
    with s.db() as c:
        expiry = execution.heartbeat(c, job_id, first['attempt_token'])
        row = execution.current(c, job_id, first['attempt_token'])
        assert expiry == row['lease_expires_at']
        assert 0 < expiry - execution.now(c) <= 30


def test_expired_attempt_cannot_write_or_renew_before_or_after_takeover(job_id):
    first = claim(job_id); expire(job_id)
    with pytest.raises(execution.LostAttempt), s.db() as c:
        execution.heartbeat(c, job_id, first['attempt_token'])
    second = claim(job_id, 'worker-b')
    assert second['attempt_number'] == 2
    assert second['attempt_token'] != first['attempt_token']
    with pytest.raises(execution.LostAttempt), s.db() as c:
        execution.current(c, job_id, first['attempt_token'])
        c.execute("UPDATE jobs SET result='{}' WHERE id=%s", (job_id,))
    with s.db() as c:
        assert execution.current(c, job_id, second['attempt_token'])['result'] is None


def test_expired_submission_is_unknown_and_not_claimable(job_id):
    claim(job_id); expire(job_id, 'submitting')
    assert claim(job_id, 'worker-b') is None
    assert claim(job_id, 'worker-c') is None
    with s.db() as c:
        row = c.execute('SELECT * FROM jobs WHERE id=%s', (job_id,)).fetchone()
        assert row['execution_phase'] == 'submission_unknown'
        assert row['status'] == 'interrupted'
        assert row['attempt_number'] == 1


def test_known_handle_survives_takeover_without_reopening_submit(job_id):
    claim(job_id)
    with s.db() as c:
        c.execute("UPDATE jobs SET provider_job_id='original-handle',execution_phase='remote_running' WHERE id=%s", (job_id,))
    expire(job_id)
    second = claim(job_id, 'worker-b')
    assert second['execution_phase'] == 'remote_running'
    assert second['provider_job_id'] == 'original-handle'


@pytest.mark.parametrize('operation', ['progress', 'result', 'handle', 'attach', 'asset'])
def test_claimed_job_rejects_unguarded_adapter_writes(job_id, operation, tmp_path):
    job = claim(job_id)
    with pytest.raises(execution.LostAttempt):
        if operation == 'progress':
            s.job_update(job_id, phase='unguarded progress', progress=90)
        elif operation == 'result':
            s.job_update(job_id, result={'text': 'unguarded result'})
        elif operation == 'handle':
            s.job_update(job_id, provider_job_id='unguarded-handle')
        elif operation == 'attach':
            s.attach_provider_job_id(job_id, 'unguarded-handle')
        else:
            from PIL import Image
            from backend.providers.common import register
            path = tmp_path / 'result.png'
            Image.new('RGB', (4, 4), 'green').save(path)
            register(job, path)


def test_current_attempt_writes_but_superseded_attempt_cannot(job_id):
    first = claim(job_id)
    with execution.scope(first):
        assert s.job_update(job_id, result={'text': 'first partial'}, progress=10)
    expire(job_id)
    second = claim(job_id, 'worker-b')
    with execution.scope(second):
        assert s.job_update(job_id, result={'text': 'current partial'}, progress=30)
        assert s.attach_provider_job_id(job_id, 'current-handle') == 'running'
    for operation in (
        lambda: s.job_update(job_id, result={'text': 'late result'}, status='succeeded'),
        lambda: s.job_update(job_id, provider_job_id='late-handle'),
        lambda: s.attach_provider_job_id(job_id, 'late-handle'),
        lambda: s.job_update(job_id, progress=99),
    ):
        with pytest.raises(execution.LostAttempt), execution.scope(first):
            operation()
    with s.db() as c:
        row = c.execute('SELECT * FROM jobs WHERE id=%s', (job_id,)).fetchone()
        assert s.unpack(row)['result'] == {'text': 'current partial'}
        assert row['provider_job_id'] == 'current-handle'
        assert row['progress'] == 30
        assert 'attempt_token' not in s.unpack(row)


def test_asset_registration_rechecks_lease_after_file_copy(job_id, tmp_path, monkeypatch):
    from PIL import Image
    from backend.providers import common
    job = claim(job_id)
    path = tmp_path / 'result.png'
    Image.new('RGB', (4, 4), 'green').save(path)
    original = common.shutil.copyfile
    def copy_then_expire(source, target):
        original(source, target)
        expire(job_id)
    monkeypatch.setattr(common.shutil, 'copyfile', copy_then_expire)
    with execution.scope(job), pytest.raises(execution.LostAttempt):
        common.register(job, path)
    with s.db() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM assets WHERE metadata->>'job_id'=%s", (job_id,)).fetchone()['n'] == 0


def test_web_control_cannot_use_cancel_bypass_to_write_a_result(job_id):
    job = claim(job_id)
    with pytest.raises(ValueError):
        s.job_update(job_id, control=True, status='cancelled', result={'text': 'not allowed'})
    assert s.job_update(job_id, control=True, status='cancelled', phase='requested')
    with execution.scope(job):
        # A paid handle that raced cancellation still needs durable retention.
        assert s.attach_provider_job_id(job_id, 'paid-handle') == 'cancelled'
        assert not s.job_update(job_id, status='succeeded', result={'text': 'late'})


@pytest.mark.parametrize('method,origin', [('POST', 'https://api.example.test'),
                                         ('GET', 'https://api.example.test'), ('GET', None)])
@pytest.mark.parametrize('takeover', [False, True])
def test_expired_attempt_cannot_send_or_query_or_download(job_id, monkeypatch, method, origin, takeover):
    import httpx
    from backend import provider_egress
    from tests.egress_helpers import mock_egress
    calls = []
    mock_egress(monkeypatch, lambda request: (calls.append(request.method) or httpx.Response(200)))
    job = claim(job_id)
    with execution.scope(job), provider_egress.client(origin=origin) as client:
        assert client.request(method, 'https://api.example.test/result').status_code == 200
        expire(job_id)
        if takeover:
            assert claim(job_id, 'replacement')
        with pytest.raises(execution.LostAttempt):
            client.request(method, 'https://api.example.test/result')
    assert calls == [method]


def test_job_update_handle_cannot_replace_original_or_disappear_on_cancel(job_id):
    job = claim(job_id)
    with execution.scope(job):
        s.job_update(job_id, provider_job_id='first-handle')
        with pytest.raises(ValueError, match='冲突'):
            s.job_update(job_id, provider_job_id='different-handle')
    with s.db() as c:
        assert c.execute('SELECT provider_job_id FROM jobs WHERE id=%s', (job_id,)).fetchone()['provider_job_id'] == 'first-handle'


def test_legacy_adapter_handle_survives_control_cancellation(job_id):
    job = claim(job_id)
    s.job_update(job_id, control=True, status='cancelled')
    with execution.scope(job):
        s.job_update(job_id, provider_job_id='paid-before-cancel')
    with s.db() as c:
        assert c.execute('SELECT provider_job_id FROM jobs WHERE id=%s', (job_id,)).fetchone()['provider_job_id'] == 'paid-before-cancel'


def test_hc_mapping_refuses_late_attempt(job_id):
    from backend.providers import hc_atom
    job = claim(job_id)
    expire(job_id)
    with execution.scope(job), pytest.raises(execution.LostAttempt):
        hc_atom._save_asset_mapping(job, {'id': 'synthetic', 'api_key': 'synthetic'},
                                    'local-test', 'late-remote', 'test-group', 'Active')


def test_ffmpeg_child_is_reaped_when_attempt_is_lost(job_id, tmp_path, monkeypatch):
    from backend.worker import Worker
    import backend.worker as worker_module
    job = claim(job_id)
    class Child:
        returncode = None
        terminated = False
        waited = False
        def poll(self): return self.returncode
        def terminate(self): self.terminated=True;self.returncode=-1
        def wait(self, timeout): self.waited=True;return self.returncode
    child = Child()
    def start(*args, **kwargs):
        expire(job_id)
        return child
    monkeypatch.setattr(worker_module.subprocess,'Popen',start)
    with execution.scope(job), pytest.raises(execution.LostAttempt):
        Worker().run_process(job,['fake-ffmpeg'],tmp_path/'ffmpeg.log','render')
    assert child.terminated and child.waited


def planned(job_id, count=1):
    with s.db() as c:
        execution.plan_steps(c,job_id,[{'name':f'text-{index}','kind':'text','units':1} for index in range(count)])
    return claim(job_id)


def begin(job, name='text-0', payload=None):
    with execution.scope(job), s.db() as c:
        return execution.begin_step(c,job['id'],name,payload or {'prompt':'frozen input'})


def checkpoint(job, name='text-0', **kwargs):
    with execution.scope(job), s.db() as c:
        execution.checkpoint_step(c,job['id'],name,**kwargs)


def test_sync_response_checkpoint_replays_without_generation(job_id):
    job = planned(job_id)
    calls=[]
    def generate(job):
        saved=begin(job)
        if saved:return saved['response']
        calls.append('POST')
        result={'text':'durable generated text'}
        checkpoint(job,response=result)
        return result
    first=generate(job)
    expire(job_id)
    replacement=claim(job_id,'replacement')
    assert replacement['execution_phase']=='finalizing'
    assert generate(replacement)==first
    assert calls==['POST']
    # A later registration failure does not reopen the generation step.
    assert generate(replacement)==first and calls==['POST']


def test_crash_in_send_window_preserves_unknown_and_blocks_new_step(job_id):
    job=planned(job_id,2)
    assert begin(job) is None
    with pytest.raises(execution.SubmissionUnknown):begin(job)
    with pytest.raises(execution.SubmissionUnknown):begin(job,'text-1')
    expire(job_id)
    assert claim(job_id,'replacement') is None
    with s.db() as c:
        steps=c.execute('SELECT name,state FROM job_steps WHERE job_id=%s ORDER BY name',(job_id,)).fetchall()
    assert [step['state'] for step in steps]==['unknown','planned']


def test_async_handle_checkpoint_is_atomic_and_recovery_returns_original(job_id):
    job=planned(job_id)
    begin(job)
    checkpoint(job,provider_job_id='original-handle')
    expire(job_id)
    replacement=claim(job_id,'replacement')
    saved=begin(replacement)
    assert saved['state']=='accepted' and saved['provider_job_id']=='original-handle'
    assert replacement['provider_job_id']=='original-handle'
    with pytest.raises(execution.LostAttempt):checkpoint(job,response={'url':'https://example.test/late'})
    checkpoint(replacement,response={'url':'https://example.test/final'})
    with pytest.raises(ValueError,match='冲突'):
        checkpoint(replacement,response={'url':'https://example.test/different'})
    assert begin(replacement)['response']=={'url':'https://example.test/final'}


def test_steps_cannot_change_input_or_units_or_skip_planning(job_id):
    job=planned(job_id)
    with pytest.raises(ValueError,match='未预占'):begin(job,'unplanned')
    with pytest.raises(ValueError,match='冲突'),s.db() as c:
        execution.plan_steps(c,job_id,[{'name':'text-0','kind':'text','units':2}])
    begin(job)
    checkpoint(job,response={'text':'saved'})
    with pytest.raises(ValueError,match='变化'):
        begin(job,payload={'prompt':'changed'})


def test_completed_first_step_never_replayed_when_second_step_is_unknown(job_id):
    job=planned(job_id,2)
    begin(job)
    checkpoint(job,response={'text':'pass 1'})
    assert begin(job)['response']=={'text':'pass 1'}
    assert begin(job,'text-1') is None
    expire(job_id)
    assert claim(job_id,'replacement') is None
    with s.db() as c:
        rows=c.execute('SELECT state FROM job_steps WHERE job_id=%s ORDER BY name',(job_id,)).fetchall()
    assert [row['state'] for row in rows]==['completed','unknown']


def test_finalizing_takeover_reuses_asset_identity(job_id,tmp_path):
    from PIL import Image
    from backend.providers.common import register
    path=tmp_path/'result.png'
    Image.new('RGB',(4,4),'green').save(path)
    job=planned(job_id)
    begin(job);checkpoint(job,response={'data':[{'url':'https://example.test/image'}]})
    with execution.scope(job):first=register(job,path,'result.png')
    expire(job_id)
    replacement=claim(job_id,'replacement')
    with execution.scope(replacement):second=register(replacement,path,'result.png')
    assert second==first
    with s.db() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM assets WHERE metadata->>'job_id'=%s",(job_id,)).fetchone()['n']==1


def test_output_slots_distinguish_identical_images_but_reject_changed_result(job_id,tmp_path):
    from PIL import Image
    from backend.providers.common import register
    path=tmp_path/'result.png'
    Image.new('RGB',(4,4),'green').save(path)
    job=planned(job_id)
    begin(job);checkpoint(job,response={'data':[1,2]})
    with execution.scope(job):
        first=register(job,path,'first.png')
        second=register(job,path,'second.png')
    assert first['id']!=second['id']
    Image.new('RGB',(4,4),'red').save(path)
    with execution.scope(job),pytest.raises(ValueError,match='冲突'):
        register(job,path,'first.png')
