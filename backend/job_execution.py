"""DEFERRED old P6 task lease experiments, not used by P6-SINGLE-01 runtime.

These primitives are being integrated for P6. They never perform network I/O,
adopt creative content, or imply that fencing can undo a dispatched request.
"""
from __future__ import annotations

import secrets
import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar

from . import store as s
from .provider_redaction import scrub

_ATTEMPT = ContextVar('job_attempt', default=None)
_OUTPUT_INDEX = ContextVar('job_output_index', default=0)


@contextmanager
def scope(job):
    """Propagate the server-issued attempt through synchronous adapter calls."""
    marker = _ATTEMPT.set((job['id'], job.get('attempt_token')))
    outputs = _OUTPUT_INDEX.set(0)
    try:
        yield
    finally:
        _OUTPUT_INDEX.reset(outputs)
        _ATTEMPT.reset(marker)


def next_output_key():
    """Stable ordered result slot when replaying a checkpointed adapter result.

    Identical bytes in two different requested slots remain two outputs. The
    stored content hash detects an adapter incorrectly replaying another result
    into a slot; legacy unclaimed fixtures retain their original behavior.
    """
    marker=_ATTEMPT.get()
    if marker is None or not marker[1]:return None
    index=_OUTPUT_INDEX.get()
    _OUTPUT_INDEX.set(index+1)
    return f'output-{index}'


def guard(connection, job_id):
    """Existing write helpers call this inside their own write transaction.

    Legacy unclaimed fixtures have no execution authority to revoke. Once a
    job has been claimed, absence of context fails closed, including adapters
    accidentally calling a helper without passing an explicit token.
    """
    marker = _ATTEMPT.get()
    row = connection.execute('SELECT * FROM jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
    if not row:
        raise LostAttempt('任务不存在；停止执行')
    if marker is not None:
        if marker[0] != job_id:
            raise LostAttempt('执行凭据不属于此任务')
        if row['attempt_number'] or marker[1]:
            return current(connection, job_id, marker[1])
    elif row['attempt_number']:
        raise LostAttempt('已领取任务缺少当前执行凭据，写入已拒绝')
    return row


def guard_call():
    """Fence every adapter HTTP hop, including unauthenticated downloads.

    Web/admin P4 calls have no Worker scope. No transaction crosses the network
    boundary: this prevents a *known* lost attempt from dispatching again, not
    a request already in flight when its lease subsequently expires.
    """
    marker = _ATTEMPT.get()
    if marker is not None:
        with s.db() as connection:
            guard(connection, marker[0])


class LostAttempt(InterruptedError):
    """The execution lease expired or a later claimant replaced this attempt."""


class SubmissionUnknown(RuntimeError):
    """A previous invocation may have reached upstream; never replay blindly."""


def plan_steps(connection, job_id, steps):
    """Persist immutable named work in the admission transaction.

    The admission layer also reserves these units in this transaction. This
    primitive deliberately cannot grant quota or dynamically invent work.
    """
    names = set()
    for step in steps:
        name, kind, units = step['name'], step['kind'], step['units']
        if (not isinstance(name,str) or not name or len(name)>120 or name in names or
                kind not in ('text','image','video','audio','export') or type(units) is not int or units<1):
            raise ValueError('任务子步骤计划无效')
        names.add(name)
        connection.execute('''INSERT INTO job_steps(job_id,name,kind,units) VALUES(%s,%s,%s,%s)
            ON CONFLICT(job_id,name) DO NOTHING''',(job_id,name,kind,units))
        row=connection.execute('SELECT kind,units FROM job_steps WHERE job_id=%s AND name=%s',
                               (job_id,name)).fetchone()
        if (row['kind'],row['units'])!=(kind,units):
            raise ValueError('任务子步骤计划冲突，不能静默重绑')


def request_hash(value):
    canonical=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def begin_step(connection, job_id, name, effective_request):
    """Persist the send boundary; caller commits BEFORE any external I/O.

    Returns a checkpoint for accepted/completed work, otherwise None grants
    exactly this attempt its first dispatch. Permission/quota admission must
    run in the same transaction before this primitive is called.
    """
    from . import job_admission,job_quota
    job_admission.lock(connection)
    job=guard(connection,job_id)
    if job['status']!='running':raise InterruptedError('任务已停止，禁止新调用')
    row=connection.execute('SELECT * FROM job_steps WHERE job_id=%s AND name=%s FOR UPDATE',
                           (job_id,name)).fetchone()
    if not row:raise ValueError('未预占的任务子步骤，禁止新增调用')
    fingerprint=request_hash(effective_request)
    if row['request_hash'] and row['request_hash']!=fingerprint:
        raise ValueError('任务子步骤请求已变化，禁止使用原步骤重投')
    if row['state'] in ('accepted','completed'):
        return {**row,'response':json.loads(row['response']) if row['response'] is not None else None}
    if row['state']!='planned':raise SubmissionUnknown('上游是否受理尚不明确，请人工核对，禁止重发')
    pending=connection.execute("""SELECT name FROM job_steps WHERE job_id=%s
        AND state IN ('submitting','unknown','accepted') LIMIT 1""",(job_id,)).fetchone()
    if pending:raise SubmissionUnknown('此前子步骤未完成，禁止新增调用')
    usage=connection.execute('SELECT * FROM job_step_usage WHERE job_id=%s AND name=%s',(job_id,name)).fetchone()
    if usage:
        if usage['state']!='reserved':raise ValueError('子步骤没有可使用的预占额度')
        reservation=connection.execute('SELECT * FROM job_reservations WHERE job_id=%s',(job_id,)).fetchone()
        job_quota.assert_unpaused(job_quota.settings(connection)['settings'],reservation['provider_id'])
        connection.execute("UPDATE job_step_usage SET state='submitted',remote_open=%s WHERE job_id=%s AND name=%s",
                           (row['kind']!='export',job_id,name))
    elif job['submission_namespace']!='legacy':
        raise ValueError('子步骤缺少预占额度，禁止新增调用')
    stamp=now(connection)
    connection.execute("""UPDATE job_steps SET state='submitting',request_hash=%s,submitted_at=%s
        WHERE job_id=%s AND name=%s""",(fingerprint,stamp,job_id,name))
    connection.execute("UPDATE jobs SET execution_phase='submitting',updated=%s WHERE id=%s",(stamp,job_id))
    return None


def checkpoint_step(connection, job_id, name, *, response=None, provider_job_id=None):
    """Save a response/handle before download, probing or asset registration.

    The same guarded transaction saves asynchronous handles on the job. Even
    cancellation must retain a paid response; it does not undo a sent request.
    """
    from . import job_admission
    job_admission.lock(connection)
    job=guard(connection,job_id)
    row=connection.execute('SELECT * FROM job_steps WHERE job_id=%s AND name=%s FOR UPDATE',
                           (job_id,name)).fetchone()
    if not row or row['state'] not in ('submitting','accepted','completed'):
        raise ValueError('子步骤没有可归档的提交')
    if provider_job_id is not None:
        if row['provider_job_id'] and row['provider_job_id']!=provider_job_id:
            raise ValueError('供应商任务编号冲突，请人工核对')
        s._attach_provider_handle(connection,job,provider_job_id)
    if response is None and provider_job_id is None:raise ValueError('缺少可恢复的上游结果或编号')
    value=scrub(response)
    if row['state']=='completed':
        if response is not None and json.loads(row['response'])!=value:
            raise ValueError('上游终态结果冲突，保留原结果')
        return
    stamp=now(connection)
    state='completed' if response is not None else 'accepted'
    if response is not None:
        connection.execute('UPDATE job_step_usage SET remote_open=FALSE WHERE job_id=%s AND name=%s',(job_id,name))
    connection.execute('''UPDATE job_steps SET state=%s,response=%s,
        provider_job_id=COALESCE(provider_job_id,%s),completed_at=%s WHERE job_id=%s AND name=%s''',
        (state,s.dumps(value) if response is not None else None,provider_job_id,
         stamp if response is not None else None,job_id,name))
    connection.execute('UPDATE jobs SET execution_phase=%s,updated=%s WHERE id=%s',
                       ('finalizing' if response is not None else 'remote_running',stamp,job_id))


def now(connection):
    return float(connection.execute(
        'SELECT EXTRACT(EPOCH FROM clock_timestamp()) AS now').fetchone()['now'])


def current(connection, job_id, token):
    """Lock then validate. Callers keep this transaction for the guarded write."""
    row = connection.execute('SELECT * FROM jobs WHERE id=%s FOR UPDATE', (job_id,)).fetchone()
    if (not row or not token or row['attempt_token'] != token or
            not row['lease_expires_at'] or row['lease_expires_at'] <= now(connection)):
        raise LostAttempt('任务执行租约已失效；旧执行者停止写入和新调用')
    return row


def claim(connection, job_id, worker_id, *, lease_seconds=30):
    """Claim one locked scheduler candidate; None means ineligible/busy.

    The scheduler/admission layer must check dependencies and capacity before
    this call in the same transaction. It may select with SKIP LOCKED. A lost
    submit response is never converted into permission to submit again.
    """
    if not worker_id or not 1 <= lease_seconds <= 300:
        raise ValueError('invalid worker identity or lease duration')
    row = connection.execute('SELECT * FROM jobs WHERE id=%s FOR UPDATE SKIP LOCKED',
                             (job_id,)).fetchone()
    if not row or row['status'] not in ('queued', 'running'):
        return None
    stamp = now(connection)
    if row['lease_expires_at'] and row['lease_expires_at'] > stamp:
        return None
    phase = row['execution_phase']
    if phase in ('submitting', 'submission_unknown') or (phase == 'legacy' and row['status'] == 'running' and not row['provider_job_id']):
        connection.execute("UPDATE job_steps SET state='unknown' WHERE job_id=%s AND state='submitting'",(job_id,))
        connection.execute("""UPDATE jobs SET status='interrupted',execution_phase='submission_unknown',
            phase='上游是否受理尚不明确；禁止自动重发，请管理员核对',updated=%s WHERE id=%s""", (stamp, job_id))
        if row['attempt_token']:
            connection.execute("""UPDATE job_attempts SET ended_at=%s,outcome='submission_unknown'
                WHERE token=%s AND ended_at IS NULL""", (stamp, row['attempt_token']))
        s.event(row['project_id'], {'type': 'job', 'id': job_id}, connection=connection)
        return None
    if row['provider_job_id']:
        phase = 'finalizing' if phase == 'finalizing' else 'remote_running'
    elif phase in ('queued', 'claimed', 'preflight') or (phase == 'legacy' and row['status'] == 'queued'):
        phase = 'claimed'
    elif phase != 'finalizing':
        return None
    if row['attempt_token']:
        connection.execute("""UPDATE job_attempts SET ended_at=%s,outcome='lease_expired'
            WHERE token=%s AND ended_at IS NULL""", (stamp, row['attempt_token']))
    token = secrets.token_hex(24)
    number = row['attempt_number'] + 1
    expires = stamp + lease_seconds
    connection.execute('''INSERT INTO job_attempts
        (job_id,number,token,worker_id,claimed_at,heartbeat_at,lease_expires_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s)''',
        (job_id, number, token, worker_id, stamp, stamp, expires))
    updated = connection.execute('''UPDATE jobs SET status='running',worker_id=%s,attempt_token=%s,
        attempt_number=%s,lease_expires_at=%s,heartbeat_at=%s,execution_phase=%s,
        started=COALESCE(started,%s),updated=%s WHERE id=%s RETURNING *''',
        (worker_id, token, number, expires, stamp, phase, stamp, stamp, job_id)).fetchone()
    return s.unpack(updated, execution=True)


def heartbeat(connection, job_id, token, *, lease_seconds=30):
    if not 1 <= lease_seconds <= 300:
        raise ValueError('invalid lease duration')
    row = current(connection, job_id, token)
    if row['status'] != 'running':
        raise LostAttempt('任务已不处于运行状态')
    stamp = now(connection)
    expires = stamp + lease_seconds
    connection.execute('UPDATE jobs SET heartbeat_at=%s,lease_expires_at=%s WHERE id=%s',
                       (stamp, expires, job_id))
    connection.execute('UPDATE job_attempts SET heartbeat_at=%s,lease_expires_at=%s WHERE token=%s',
                       (stamp, expires, token))
    return expires
