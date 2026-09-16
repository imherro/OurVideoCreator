"""P1 acceptance: real Web/Worker processes sharing one isolated data dir."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
CREATE_FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_json(url, opener=None, timeout=15):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            response = (opener or build_opener()).open(url, timeout=1)
            return json.loads(response.read())
        except (OSError, URLError, json.JSONDecodeError) as exc:
            last = exc
            time.sleep(0.1)
    raise AssertionError(f'timed out waiting for {url}: {last}')


def json_request(opener, url, method='GET', body=None, csrf_token=None):
    payload = None if body is None else json.dumps(body).encode()
    headers={'Content-Type':'application/json'}
    if csrf_token:headers['X-CSRF-Token']=csrf_token
    request = Request(url, data=payload, method=method, headers=headers)
    with opener.open(request, timeout=5) as response:
        return json.loads(response.read())


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def wait_until(predicate, message, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError(message)


def test_two_webs_independent_worker_restart_and_single_worker_lock(tmp_path):
    started_at = time.monotonic()
    data = tmp_path / 'p1-data'
    data.mkdir()
    env = {**os.environ, 'MVC_DATA_DIR':str(data), 'PYTHONUTF8':'1', 'NO_PROXY':'127.0.0.1,localhost'}
    fake_port, web_one_port, web_two_port = free_port(), free_port(), free_port()
    env['OVC_PROVIDER_EGRESS_EXCEPTIONS']=json.dumps([{'scheme':'http','host':'127.0.0.1','ip':'127.0.0.1','port':fake_port}])
    count_file = tmp_path / 'fake-count.txt'
    received_file = tmp_path / 'fake-received.json'
    release_file = tmp_path / 'fake-release'
    processes = []
    log_paths = {}
    job_id = None
    phase = 'initializing'
    last_request = None
    csrf_token = None

    def request_json(opener, url, method='GET', body=None):
        nonlocal last_request
        request_started = time.monotonic()
        try:
            return json_request(opener, url, method, body, csrf_token)
        finally:
            last_request = {
                'url': url,
                'method': method,
                'elapsed_seconds': round(time.monotonic() - request_started, 3),
            }

    def diagnostics(status, error=None):
        child_logs = {
            name: {
                'stdout': stdout.read_text(encoding='utf-8', errors='replace'),
                'stderr': stderr.read_text(encoding='utf-8', errors='replace'),
            }
            for name, (stdout, stderr) in log_paths.items()
        }
        database = task = None
        try:
            from backend.database import check_ready
            database = check_ready()
            if job_id:
                from backend import store
                with store.db() as connection:
                    row = connection.execute(
                        'SELECT id,status,phase,provider_job_id,updated FROM jobs WHERE id=%s',
                        (job_id,),
                    ).fetchone()
                    task = dict(row) if row else None
        except Exception as exc:
            database = {'diagnostic_error': f'{exc.__class__.__name__}: {exc}'}
        return {
            'status': status,
            'phase': phase,
            'error': error,
            'elapsed_seconds': round(time.monotonic() - started_at, 3),
            'last_request': last_request,
            'database': database,
            'task': task,
            'child_logs': child_logs,
        }

    def spawn(name, command):
        stdout_path, stderr_path = tmp_path/f'{name}.stdout.log', tmp_path/f'{name}.stderr.log'
        stdout = stdout_path.open('w', encoding='utf-8')
        stderr = stderr_path.open('w', encoding='utf-8')
        process = subprocess.Popen(
            command, cwd=ROOT, env=env, stdout=stdout, stderr=stderr,
            creationflags=CREATE_FLAGS,
        )
        stdout.close()
        stderr.close()
        processes.append(process)
        log_paths[name] = (stdout_path, stderr_path)
        return process

    try:
        from tests.auth_helpers import ADMIN_PASSWORD, ADMIN_PHONE, ensure_test_admin
        ensure_test_admin()
        phase = 'starting fake provider'
        fake = spawn('fake-provider', [
            sys.executable, str(ROOT/'tests'/'fake_provider_server.py'),
            '--port', str(fake_port), '--count-file', str(count_file),
            '--received-file', str(received_file), '--release-file', str(release_file),
        ])

        def web(port, name):
            process = spawn(name, [
                sys.executable, '-m', 'uvicorn', 'backend.app:app',
                '--host', '127.0.0.1', '--port', str(port),
            ])
            wait_json(f'http://127.0.0.1:{port}/api/health')
            return process

        phase = 'starting two web processes'
        web_one, web_two = web(web_one_port, 'web-one'), web(web_two_port, 'web-two')
        assert web_one.poll() is None and web_two.poll() is None
        assert not (data/'worker.lock').exists(), 'Web must not acquire the Worker lock'

        cookie_jar = CookieJar()
        opener = build_opener(HTTPCookieProcessor(cookie_jar))
        base_one = f'http://127.0.0.1:{web_one_port}'
        base_two = f'http://127.0.0.1:{web_two_port}'
        phase = 'authenticating and enqueueing'
        assert request_json(opener, base_one+'/api/auth/login', 'POST', {
            'phone':ADMIN_PHONE,'password':ADMIN_PASSWORD,
        })['ok']
        csrf_token=next(cookie.value for cookie in cookie_jar if cookie.name=='ovc_csrf')
        provider = request_json(opener, base_one+'/api/admin/model-providers', 'POST', {
            'revision':0,'name':'P1 Fake','enabled':True,'api_key':'',
            'config':{'type':'openai','url':f'http://127.0.0.1:{fake_port}/v1','auth_mode':'none'},
        })
        model = request_json(opener, base_one+'/api/admin/models', 'POST', {
            'revision':0,'provider_id':provider['id'],'kind':'text','published':True,'enabled':True,
            'definition':{'name':'P1 text','upstream_model':'p1-fake-model','capabilities':{},'defaults':{},'rules':{}},
        })
        project = request_json(opener, base_one+'/api/projects', 'POST', {'name':'P1 Process Test'})
        request_json(opener, base_one+f'/api/projects/{project["id"]}/objects', 'POST', {
            'kind':'node', 'content':{'node':{
                'id':'p1-text', 'type':'media', 'data':{'kind':'text'},
            }},
        })
        job = request_json(opener, base_one+f'/api/projects/{project["id"]}/jobs', 'POST', {
            'node_id':'p1-text','kind':'text','submission_id':'p1-process-job-001',
            'input':{'model_id':model['id'],'prompt':'process isolation'},
        })
        job_id = job['id']
        assert job['status'] == 'queued'

        phase = 'waiting for worker/provider handoff'
        worker = spawn('worker', [sys.executable, '-m', 'backend.worker_cli', '--concurrency', '1'])
        wait_until(lambda: received_file.exists(), 'Worker never reached the fake Provider')

        def running_job():
            value = request_json(opener, base_two+f'/api/jobs/{job["id"]}')
            return value if value['status'] == 'running' else None

        running_before = wait_until(
            running_job,
            'Job never entered running state',
        )
        assert running_before['started'] is not None
        assert count_file.read_text(encoding='utf-8') == '1'
        worker_pid = worker.pid

        stop(web_one)
        assert worker.poll() is None, 'stopping Web must not stop Worker'
        restarted_web = web(web_one_port, 'web-one-restarted')
        assert restarted_web.pid != web_one.pid

        running_after = request_json(opener, base_one+f'/api/jobs/{job["id"]}')
        assert running_after['status'] == 'running'
        assert running_after['started'] == running_before['started']
        assert worker.poll() is None and worker.pid == worker_pid
        assert count_file.read_text(encoding='utf-8') == '1'

        release_file.write_text('release', encoding='utf-8')

        deadline = time.time()+15
        current = None
        while time.time()<deadline:
            current = request_json(opener, base_two+f'/api/jobs/{job["id"]}')
            if current['status'] == 'succeeded':
                break
            time.sleep(.1)
        assert current['status'] == 'succeeded'
        assert current['started'] == running_before['started']
        assert current['result']['text'] == 'P1 fake response'
        assert count_file.read_text(encoding='utf-8') == '1'

        contender = subprocess.run(
            [sys.executable, '-m', 'backend.worker_cli', '--concurrency', '1'],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', timeout=10, creationflags=CREATE_FLAGS,
        )
        assert contender.returncode == 2
        assert 'refused to start' in contender.stderr and 'already has a Worker' in contender.stderr
        phase = 'complete'
        print(json.dumps({**diagnostics('passed'),
            'web_pids':[web_one.pid,web_two.pid,restarted_web.pid],
            'worker_pid':worker_pid,'job_id':job['id'],
            'running_before_web_restart':running_before,
            'running_after_web_restart':running_after,
            'final_job':current,
            'fake_request_count':1,'second_worker_exit':contender.returncode,
        }, ensure_ascii=False))
    except BaseException as exc:
        print(json.dumps(diagnostics('failed', f'{exc.__class__.__name__}: {exc}'), ensure_ascii=False))
        raise
    finally:
        for process in reversed(processes):
            stop(process)
