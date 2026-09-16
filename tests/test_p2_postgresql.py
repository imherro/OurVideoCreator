from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy.engine import make_url

from backend import store as s
from backend.app import SourceExtractionCreate, app
from backend.database import WorkerAdvisoryLock, check_ready
from tests.postgres_test_db import _assert_safe_target
from tests.auth_helpers import login_admin
from tests.platform_model_helpers import publish_test_model
from tests.test_p3_r2_interleavings import wait_for_db_waiters


ROOT = Path(__file__).resolve().parents[1]


def authenticated_client():
    client = TestClient(app)
    client.__enter__()
    login_admin(client)
    return client


def create_project(client, name='P2 PostgreSQL'):
    response = client.post('/api/projects', json={'name': name})
    assert response.status_code == 200, response.text
    return response.json()


def test_db01_empty_database_requires_explicit_repeatable_alembic(tmp_path):
    admin = make_url(os.environ['OVC_TEST_ADMIN_URL'])
    name = f'ovc_test_empty_{uuid.uuid4().hex[:12]}'
    _assert_safe_target(name)
    admin_dsn = admin.set(drivername='postgresql').render_as_string(hide_password=False)
    target = admin.set(database=name, drivername='postgresql+psycopg')
    target_url = target.render_as_string(hide_password=False)
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    env = {**os.environ, 'OVC_DATABASE_URL': target_url, 'MVC_DATA_DIR': str(tmp_path/'media')}
    try:
        not_ready = subprocess.run(
            [sys.executable, '-c', 'from backend import store; store.init()'],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=20,
        )
        assert not_ready.returncode != 0
        assert 'schema is not initialized' in (not_ready.stdout + not_ready.stderr)
        with psycopg.connect(target.set(drivername='postgresql').render_as_string(hide_password=False)) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'"
            ).fetchone()[0] == 0

        first = subprocess.run(
            [sys.executable, '-m', 'alembic', 'upgrade', 'head'],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
        )
        second = subprocess.run(
            [sys.executable, '-m', 'alembic', 'upgrade', 'head'],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
        )
        assert first.returncode == second.returncode == 0, first.stderr + second.stderr
        ready = subprocess.run(
            [sys.executable, '-c', 'from backend import store; print(store.init())'],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=20,
        )
        assert ready.returncode == 0, ready.stderr
        assert "'server_version': '18.6'" in ready.stdout
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                'SELECT pg_terminate_backend(pid) FROM pg_stat_activity '
                'WHERE datname=%s AND pid<>pg_backend_pid()', (name,),
            )
            _assert_safe_target(name)
            connection.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


def test_db02_missing_and_non_postgresql_dsn_fail_without_fallback(tmp_path):
    base = {**os.environ, 'MVC_DATA_DIR': str(tmp_path/'no-fallback')}
    missing = dict(base)
    missing.pop('OVC_DATABASE_URL', None)
    result = subprocess.run(
        [sys.executable, '-c', 'from backend import store; store.init()'],
        cwd=ROOT, env=missing, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode != 0
    assert 'OVC_DATABASE_URL is required' in (result.stdout + result.stderr)
    sqlite = {**base, 'OVC_DATABASE_URL': 'sqlite:///forbidden.sqlite'}
    result = subprocess.run(
        [sys.executable, '-c', 'from backend import store; store.init()'],
        cwd=ROOT, env=sqlite, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode != 0
    assert 'SQLite fallback is disabled' in (result.stdout + result.stderr)
    assert not (tmp_path/'no-fallback'/'studio.sqlite').exists()


def test_db03_two_connections_same_revision_yield_one_success_one_conflict():
    client = authenticated_client()
    try:
        project = create_project(client, 'P2 concurrent save')
        body = {'expected_revision': project['revision'], 'patch': {'name': 'P2 concurrent winner'}}
        barrier = threading.Barrier(3)
        outcomes = []
        lock = threading.Lock()

        def contender(index):
            local = copy.deepcopy(body)
            local['patch']['brief'] = f'contender-{index}'
            barrier.wait()
            response = client.patch(f'/api/projects/{project["id"]}/metadata', json=local)
            outcome = ('success', response.json()['revision']) if response.status_code == 200 else ('conflict', response.status_code)
            with lock:
                outcomes.append(outcome)

        threads = [threading.Thread(target=contender, args=(index,)) for index in (1, 2)]
        with s.db() as blocker:
            blocker.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE', (project['id'],))
            for thread in threads:
                thread.start()
            barrier.wait()
            waits = wait_for_db_waiters(2)
            assert all(row['blockers'] for row in waits)
            print('P2 metadata concurrent save PostgreSQL trace:', waits)
        for thread in threads:
            thread.join(timeout=20)
            assert not thread.is_alive()
        assert sorted(outcomes) == [('conflict', 409), ('success', 2)]
        with s.db() as connection:
            row = connection.execute(
                'SELECT revision,document FROM projects WHERE id=%s', (project['id'],)
            ).fetchone()
            history = connection.execute(
                'SELECT COUNT(*) count FROM revisions WHERE project_id=%s', (project['id'],)
            ).fetchone()['count']
            events = connection.execute(
                "SELECT COUNT(*) count FROM events WHERE project_id=%s AND payload->>'type'='project'",
                (project['id'],),
            ).fetchone()['count']
        assert row['revision'] == 2
        assert json.loads(row['document'])['brief'] in {'contender-1', 'contender-2'}
        assert history == events == 1
    finally:
        client.__exit__(None, None, None)


def test_db04_injected_save_failure_rolls_back_content_history_and_event(monkeypatch):
    client = authenticated_client()
    try:
        project = create_project(client, 'P2 rollback')
        body = {'expected_revision': project['revision'],
            'patch': {'name': 'must roll back', 'brief': 'must not persist'}}
        with s.db() as connection:
            before_events = connection.execute('SELECT COUNT(*) count FROM events WHERE project_id=%s',
                (project['id'],)).fetchone()['count']

        def fail_event(*_args, **kwargs):
            assert kwargs.get('connection') is not None
            raise RuntimeError('injected event failure')

        monkeypatch.setattr(s, 'event', fail_event)
        with pytest.raises(RuntimeError, match='injected event failure'):
            client.patch(f'/api/projects/{project["id"]}/metadata', json=body)
        with s.db() as connection:
            row = connection.execute(
                'SELECT revision,document FROM projects WHERE id=%s', (project['id'],)
            ).fetchone()
            history = connection.execute(
                'SELECT COUNT(*) count FROM revisions WHERE project_id=%s', (project['id'],)
            ).fetchone()['count']
            events = connection.execute(
                'SELECT COUNT(*) count FROM events WHERE project_id=%s', (project['id'],)
            ).fetchone()['count']
        assert row['revision'] == 1
        assert json.loads(row['document']).get('brief') != 'must not persist'
        assert history == 0 and events == before_events
    finally:
        client.__exit__(None, None, None)


def test_db04_last_batch_item_failure_rolls_back_jobs_private_rows_and_events(monkeypatch):
    client = authenticated_client()
    model = publish_test_model(client, 'p2-batch-model')
    try:
        production = client.post('/api/productions', json={'name': 'P2 batch rollback'}).json()
        episode = client.post(f'/api/productions/{production["id"]}/episodes', json={'title': 'Episode'}).json()
        source = client.post(
            f'/api/productions/{production["id"]}/sources',
            json={'title': 'Source', 'type': 'manual', 'metadata': {}},
        ).json()
        chapters = [
            client.post(
                f'/api/productions/{production["id"]}/sources/{source["id"]}/chapters',
                json={'title': f'Chapter {index}', 'content': f'content {index}'},
            ).json()
            for index in (1, 2)
        ]
        import backend.app as app_module
        original = app_module.create_job_record
        calls = {'count': 0}

        def injected(connection, project_id, body):
            calls['count'] += 1
            if calls['count'] == 2:
                raise RuntimeError('injected last batch item failure')
            return original(connection, project_id, body)

        monkeypatch.setattr(app_module, 'create_job_record', injected)
        body = SourceExtractionCreate(
            project_id=episode['id'], chapter_ids=[item['id'] for item in chapters],
            model_id=model['id'], allow_cloud=False,
            submission_id='p2-last-item-rollback',
        )
        with pytest.raises(RuntimeError, match='last batch item'):
            client.post(f'/api/productions/{production["id"]}/source-extractions', json=body.model_dump())
        with s.db() as connection:
            jobs = connection.execute(
                'SELECT COUNT(*) count FROM jobs WHERE submission_id LIKE %s',
                ('p2-last-item-rollback%',),
            ).fetchone()['count']
            private = connection.execute(
                'SELECT COUNT(*) count FROM job_private jp JOIN jobs j ON j.id=jp.job_id '
                'WHERE j.submission_id LIKE %s', ('p2-last-item-rollback%',),
            ).fetchone()['count']
            events = connection.execute(
                "SELECT COUNT(*) count FROM events WHERE project_id=%s AND payload->>'type'='job'",
                (episode['id'],),
            ).fetchone()['count']
        assert jobs == private == events == 0
    finally:
        client.__exit__(None, None, None)


def test_db05_data_persists_across_readiness_restart_and_reset_guard_rejects_user_db():
    client = authenticated_client()
    try:
        project = create_project(client, 'P2 persistence')
        now = time.time()
        job_id = s.uid('job-')
        with s.db() as connection:
            connection.execute(
                "INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated) "
                "VALUES(%s,%s,%s,%s,'text','queued',%s,%s,%s)",
                (job_id, job_id, project['id'], 'persist-node', s.dumps({'prompt': 'persist'}), now, now),
            )
        identity = check_ready()
        s.init()
        with s.db() as connection:
            assert connection.execute(
                'SELECT status FROM jobs WHERE id=%s', (job_id,)
            ).fetchone()['status'] == 'queued'
        assert identity['database_name'].startswith('ovc_test_')
        with pytest.raises(RuntimeError, match='Refusing test database operation'):
            _assert_safe_target('postgres')
        with pytest.raises(RuntimeError, match='Refusing test database operation'):
            _assert_safe_target('our_video_creator')
    finally:
        client.__exit__(None, None, None)


def test_single_worker_lock_is_database_scoped_not_media_directory(monkeypatch, tmp_path):
    first, second = WorkerAdvisoryLock(), WorkerAdvisoryLock()
    first.acquire()
    try:
        monkeypatch.setenv('MVC_DATA_DIR', str(tmp_path/'different-media-directory'))
        with pytest.raises(RuntimeError, match='already has a Worker'):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()


def test_runtime_and_active_scripts_have_no_sqlite_path_or_sql_dialect():
    forbidden = ('sqlite3', 'PRAGMA', 'BEGIN IMMEDIATE', 'INSERT OR ', 'REPLACE INTO', 'lastrowid', 'studio.sqlite')
    offenders = []
    for folder in (ROOT/'backend', ROOT/'scripts'):
        for path in folder.rglob('*.py'):
            text = path.read_text(encoding='utf-8')
            for token in forbidden:
                if token in text:
                    offenders.append(f'{path.relative_to(ROOT)}:{token}')
    assert offenders == []


@pytest.mark.skipif(os.name != 'nt', reason='PowerShell lifecycle is Windows-only')
def test_stop_ownership_does_not_connect_to_offline_database(tmp_path):
    env = {
        **os.environ,
        'MVC_DATA_DIR': str(tmp_path/'offline-stop'),
        'OVC_DATABASE_URL': 'postgresql+psycopg://offline@127.0.0.1:1/ovc_offline',
        'PYTHONUTF8': '1',
    }
    result = subprocess.run(
        ['powershell.exe', '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass',
         '-File', str(ROOT/'Stop-Studio.ps1'), '-WorkerOnly'],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'nothing stopped' in result.stdout


def test_instance_identity_includes_database_but_never_credentials(tmp_path):
    base = {**os.environ, 'MVC_DATA_DIR': str(tmp_path/'same-media')}
    values = []
    for database in ('ovc_identity_a', 'ovc_identity_b'):
        env = {
            **base,
            'OVC_DATABASE_URL': f'postgresql+psycopg://identity:super-secret@127.0.0.1:5432/{database}',
        }
        result = subprocess.run(
            [sys.executable, '-m', 'backend.instance_identity'],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0, result.stderr
        assert 'super-secret' not in result.stdout
        values.append(json.loads(result.stdout))
    assert values[0]['instance_id'] != values[1]['instance_id']
    assert values[0]['data_dir'] == values[1]['data_dir']
