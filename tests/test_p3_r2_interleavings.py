"""Real PostgreSQL/HTTP schedules and red/green evidence for P3-R2."""
from __future__ import annotations

import concurrent.futures
import json
import socket
import threading
import time
from contextlib import contextmanager

import httpx
import pytest
import uvicorn

from backend import identity, store as s
from backend.app import app
from tests.test_p3_identity_acl import admin, clients, clear_auth_rate_limits, register


def wait_for_db_waiters(count, alternate=None):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with s.db() as c:
            rows = c.execute("""SELECT pid,wait_event_type,wait_event,pg_blocking_pids(pid) blockers
                FROM pg_stat_activity WHERE datname=current_database()
                AND application_name='our-video-creator' AND wait_event_type='Lock'""").fetchall()
        if len(rows) >= count:
            return [dict(r) for r in rows]
        if alternate is not None and alternate.is_set():
            return []
        time.sleep(0.02)
    raise AssertionError(f'Expected {count} database waiters, observed {rows}')


@contextmanager
def live_http():
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', ws='none'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]})
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        yield f'http://127.0.0.1:{port}'
    finally:
        server.should_exit = True
        thread.join(15)
        sock.close()
        assert not thread.is_alive()


@pytest.mark.parametrize('initial', ['absent', 'expired', 'cleared'])
def test_first_bucket_http_waiters_respect_budget(admin, clients, monkeypatch, initial):
    _, _, phone = register(admin, clients, nickname='HTTP rate test')
    keys = ['login:ip:127.0.0.1', 'login:account:' + identity.digest(identity.normalize_phone(phone))]
    with s.db() as c:
        c.execute('DELETE FROM auth_rate_limits')
        if initial != 'absent':
            for key in keys:
                c.execute('INSERT INTO auth_rate_limits VALUES (%s,%s,10,%s)',
                          (key, time.time() - 301, time.time() - 1))
        if initial == 'cleared':
            identity.clear_rate_limit(c, keys)
    entered, release = threading.Event(), threading.Event()
    calls = 0
    mutex = threading.Lock()
    original = identity.verify_password

    def verify(encoded, password):
        nonlocal calls
        with mutex:
            calls += 1
            first = calls == 1
        if first:
            entered.set()
            assert release.wait(15)
        return original(encoded, password)

    monkeypatch.setattr(identity, 'verify_password', verify)
    with live_http() as url, concurrent.futures.ThreadPoolExecutor(max_workers=11) as pool:
        def login():
            with httpx.Client(base_url=url, timeout=25, trust_env=False) as client:
                return client.post('/api/auth/login', json={
                    'phone': phone, 'password': 'wrong-test-password',
                }).status_code
        first = pool.submit(login)
        try:
            assert entered.wait(10), first.result() if first.done() else 'HTTP request still pending'
            rest = [pool.submit(login) for _ in range(10)]
            waiters = wait_for_db_waiters(10)
            assert all(r['blockers'] for r in waiters)
        finally:
            release.set()
        statuses = [f.result() for f in [first, *rest]]
    with s.db() as c:
        counts = [r['attempts'] for r in c.execute(
            'SELECT attempts FROM auth_rate_limits WHERE key=ANY(%s) ORDER BY key', (keys,))]
    print(json.dumps({'scenario': initial, 'database_waiters': waiters,
                      '401': statuses.count(401), '429': statuses.count(429),
                      'verify_calls': calls, 'final_counts': counts}))
    assert sorted(statuses) == [401] * 10 + [429]
    assert calls == 10 and counts == [10, 10]


def test_reset_expiration_is_rechecked_after_user_lock(admin, clients, monkeypatch):
    _, user, _ = register(admin, clients, nickname='Expiry after wait')
    reset = admin.post('/api/admin/password-resets', json={'user_id': user['id']}).json()
    consumer = clients()
    base = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        with s.db() as c:
            c.execute('SELECT id FROM users WHERE id=%s FOR UPDATE', (user['id'],))
            future = pool.submit(consumer.post, '/api/auth/password-reset', json={
                'token': reset['token'], 'password': 'P3-R2-expiry-test-password!',
            })
            waiters = wait_for_db_waiters(1)
            # Expiry is after request start but before the lock is obtained.
            c.execute('UPDATE password_reset_tokens SET expires=%s WHERE id=%s',
                      (base + 60, reset['id']))
            monkeypatch.setattr(time, 'time', lambda: base + 61)
        response = future.result(timeout=15)
    print(json.dumps({'scenario': 'expires_while_waiting', 'status': response.status_code,
                      'database_waiters': waiters}))
    assert response.status_code == 400
    assert not consumer.get('/api/auth/status').json()['authenticated']


@pytest.mark.parametrize('scenario', ['issue_empty', 'issue_existing', 'issue_then_consume', 'consume_then_issue'])
def test_reset_http_serial_orders(admin, clients, monkeypatch, scenario):
    _, user, _ = register(admin, clients, nickname='HTTP recovery test')
    old = None
    if scenario != 'issue_empty':
        old = admin.post('/api/admin/password-resets', json={'user_id': user['id']}).json()
    entered, release = threading.Event(), threading.Event()
    original = identity.lock_password_recovery_user
    first_call = True
    mutex = threading.Lock()

    def hold_first(c, uid):
        nonlocal first_call
        row = original(c, uid)
        with mutex:
            first = first_call
            first_call = False
        if first:
            entered.set()
            assert release.wait(15)
        return row

    monkeypatch.setattr(identity, 'lock_password_recovery_user', hold_first)
    with live_http() as url, concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        def issue():
            with httpx.Client(base_url=url, trust_env=False, timeout=25,
                              cookies=dict(admin.cookies), headers={
                                  'X-CSRF-Token': admin.cookies.get(identity.CSRF_COOKIE),
                              }) as client:
                return client.post('/api/admin/password-resets', json={'user_id': user['id']})

        def consume(token):
            with httpx.Client(base_url=url, trust_env=False, timeout=25) as client:
                return client.post('/api/auth/password-reset', json={
                    'token': token, 'password': 'HTTP-recovery-test-password!',
                })

        first_action = (lambda: consume(old['token'])) if scenario == 'consume_then_issue' else issue
        second_action = (lambda: consume(old['token'])) if scenario == 'issue_then_consume' else issue
        first = pool.submit(first_action)
        try:
            assert entered.wait(10), first.result().status_code if first.done() else 'HTTP pending'
            second = pool.submit(second_action)
            waiters = wait_for_db_waiters(1)
            assert all(r['blockers'] for r in waiters)
        finally:
            release.set()
        a, b = first.result(), second.result()
        expected = [200, 400] if scenario == 'issue_then_consume' else [200, 200]
        assert [a.status_code, b.status_code] == expected
        newest = a.json() if scenario == 'issue_then_consume' else b.json()
        with s.db() as c:
            active = c.execute('''SELECT id FROM password_reset_tokens WHERE user_id=%s
                AND revoked_at IS NULL AND consumed_at IS NULL AND expires>%s''',
                (user['id'], time.time())).fetchall()
        assert [r['id'] for r in active] == [newest['id']]
        if scenario.startswith('issue_') and scenario != 'issue_then_consume':
            assert consume(a.json()['token']).status_code == 400
        if old:
            assert consume(old['token']).status_code == 400
        consume_status = consume(newest['token']).status_code
        replay_status = consume(newest['token']).status_code
        assert consume_status == 200 and replay_status == 400
    print(json.dumps({'scenario': scenario, 'database_waiters': waiters,
                      'ordered_statuses': [a.status_code, b.status_code],
                      'active_token_count': len(active), 'new_token_consume': consume_status,
                      'replay_status': replay_status}))


def test_three_login_empty_to_existing_bucket_order(admin, clients, monkeypatch):
    _, _, phone = register(admin, clients, nickname='Three request lock order')
    with s.db() as c:
        c.execute('DELETE FROM auth_rate_limits')
    entered = [threading.Event(), threading.Event()]
    release = [threading.Event(), threading.Event()]
    original = identity.verify_password
    calls = 0
    mutex = threading.Lock()

    def verify(encoded, password):
        nonlocal calls
        with mutex:
            index = calls
            calls += 1
        if index < 2:
            entered[index].set()
            assert release[index].wait(15)
        return original(encoded, password)

    monkeypatch.setattr(identity, 'verify_password', verify)
    with live_http() as url, concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        def login():
            with httpx.Client(base_url=url, trust_env=False, timeout=25) as client:
                return client.post('/api/auth/login', json={
                    'phone': phone, 'password': 'wrong-test-password',
                }).status_code
        a = pool.submit(login)
        try:
            assert entered[0].wait(10)
            b = pool.submit(login)
            waiting_b = wait_for_db_waiters(1)
            release[0].set()
            status_a = a.result(timeout=15)
            assert entered[1].wait(10)
            c = pool.submit(login)
            waiting_c = wait_for_db_waiters(1)
        finally:
            for event in release:
                event.set()
        statuses = [status_a, b.result(timeout=15), c.result(timeout=15)]
    print(json.dumps({'scenario': 'three_login_empty_to_existing',
                      'B_waits_before_A_commit': waiting_b, 'C_waits_after_A_commit': waiting_c,
                      'statuses': statuses, 'verify_calls': calls}))
    assert statuses == [401, 401, 401]
    assert calls == 3


def test_two_issuers_revoke_before_insert(admin, clients, monkeypatch):
    _, user, _ = register(admin, clients, nickname='Two issuer linearization')
    entered = [threading.Event(), threading.Event()]
    release = threading.Event()
    original_db = s.db
    calls = 0
    mutex = threading.Lock()

    class ObservedConnection:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def execute(self, query, params=None):
            nonlocal calls
            result = self.connection.execute(query, params)
            if (isinstance(query, str) and query.startswith('UPDATE password_reset_tokens SET revoked_at=')
                    and params and params[-1] == user['id']):
                with mutex:
                    index = calls
                    calls += 1
                if index < 2:
                    entered[index].set()
                    assert release.wait(15)
            return result

    @contextmanager
    def observed_db():
        with original_db() as c:
            yield ObservedConnection(c)

    monkeypatch.setattr(s, 'db', observed_db)
    with live_http() as url, concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        def issue():
            with httpx.Client(base_url=url, trust_env=False, timeout=25,
                              cookies=dict(admin.cookies), headers={
                                  'X-CSRF-Token': admin.cookies.get(identity.CSRF_COOKIE),
                              }) as client:
                return client.post('/api/admin/password-resets', json={'user_id': user['id']})
        first = pool.submit(issue)
        try:
            assert entered[0].wait(10)
            second = pool.submit(issue)
            # Old code reaches the second UPDATE while the first is paused;
            # correct code waits on the user's lock before reaching it.
            waiters = wait_for_db_waiters(1, alternate=entered[1])
            overlapped = entered[1].is_set()
        finally:
            release.set()
        responses = [first.result(), second.result()]
    with s.db() as c:
        active = c.execute('''SELECT id FROM password_reset_tokens WHERE user_id=%s
            AND revoked_at IS NULL AND consumed_at IS NULL AND expires>%s''',
            (user['id'], time.time())).fetchall()
    print(json.dumps({'scenario': 'two_issuers_between_revoke_insert',
                      'database_waiters': waiters, 'overlapping_revoke_steps': overlapped,
                      'statuses': [r.status_code for r in responses], 'active_token_count': len(active)}))
    assert [r.status_code for r in responses] == [200, 200]
    assert not overlapped and len(active) == 1


@pytest.mark.parametrize('scenario', ['login_then_reset', 'reset_then_login', 'same_token_consumers'])
def test_reset_login_session_serial_orders(admin, clients, monkeypatch, scenario):
    old_session, user, phone = register(admin, clients, nickname='Session ordering')
    from tests.test_p3_identity_acl import PASSWORD
    reset = admin.post('/api/admin/password-resets', json={'user_id': user['id']}).json()
    entered, release = threading.Event(), threading.Event()
    function_name = 'verify_password' if scenario == 'login_then_reset' else 'hash_password'
    original = getattr(identity, function_name)
    first_call = True

    def hold_first(*args):
        nonlocal first_call
        if first_call:
            first_call = False
            entered.set()
            assert release.wait(15)
        return original(*args)

    monkeypatch.setattr(identity, function_name, hold_first)
    with live_http() as url, httpx.Client(base_url=url, trust_env=False, timeout=25) as login_client, \
            httpx.Client(base_url=url, trust_env=False, timeout=25) as reset_client, \
            concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        def login():
            return login_client.post('/api/auth/login', json={'phone': phone, 'password': PASSWORD})

        def consume(client):
            return client.post('/api/auth/password-reset', json={
                'token': reset['token'], 'password': 'HTTP-new-session-password!',
            })

        first = pool.submit(login if scenario == 'login_then_reset' else lambda: consume(reset_client))
        try:
            assert entered.wait(10)
            second = pool.submit((lambda: consume(reset_client)) if scenario == 'login_then_reset'
                                 else (lambda: consume(login_client)) if scenario == 'same_token_consumers'
                                 else login)
            waiters = wait_for_db_waiters(1)
        finally:
            release.set()
        statuses = [first.result().status_code, second.result().status_code]
        expected = {'login_then_reset': [200, 200], 'reset_then_login': [200, 401],
                    'same_token_consumers': [200, 400]}[scenario]
        assert statuses == expected
        assert not old_session.get('/api/auth/status').json()['authenticated']
        assert not login_client.get('/api/auth/status').json()['authenticated']
        assert reset_client.get('/api/auth/status').json()['authenticated']
        fresh_login = login_client.post('/api/auth/login', json={
            'phone': phone, 'password': 'HTTP-new-session-password!',
        }).status_code
        assert fresh_login == 200
    print(json.dumps({'scenario': scenario, 'database_waiters': waiters, 'statuses': statuses,
                      'old_sessions_authenticated': False, 'new_password_login': fresh_login}))
