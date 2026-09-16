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


def json_request(opener, url, method='GET', body=None):
    payload = None if body is None else json.dumps(body).encode()
    request = Request(url, data=payload, method=method, headers={'Content-Type':'application/json'})
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


def test_two_webs_independent_worker_restart_and_single_worker_lock(tmp_path):
    data = tmp_path / 'p1-data'
    data.mkdir()
    env = {**os.environ, 'MVC_DATA_DIR':str(data), 'PYTHONUTF8':'1', 'NO_PROXY':'127.0.0.1,localhost'}
    fake_port, web_one_port, web_two_port = free_port(), free_port(), free_port()
    count_file = tmp_path / 'fake-count.txt'
    processes = []
    try:
        fake = subprocess.Popen(
            [sys.executable, str(ROOT/'tests'/'fake_provider_server.py'), '--port', str(fake_port), '--count-file', str(count_file), '--delay', '1.2'],
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_FLAGS,
        )
        processes.append(fake)

        def web(port):
            process = subprocess.Popen(
                [sys.executable, '-m', 'uvicorn', 'backend.app:app', '--host', '127.0.0.1', '--port', str(port)],
                cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_FLAGS,
            )
            processes.append(process)
            wait_json(f'http://127.0.0.1:{port}/api/health')
            return process

        web_one, web_two = web(web_one_port), web(web_two_port)
        assert web_one.poll() is None and web_two.poll() is None
        assert not (data/'worker.lock').exists(), 'Web must not acquire the Worker lock'

        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        base_one = f'http://127.0.0.1:{web_one_port}'
        base_two = f'http://127.0.0.1:{web_two_port}'
        assert json_request(opener, base_one+'/api/auth/setup', 'POST', {'password':'p1-process-test'})['ok']
        provider = {'id':'p1-fake','name':'P1 Fake','type':'openai','kind':'text','url':f'http://127.0.0.1:{fake_port}/v1','local':True,'model':'p1-fake-model'}
        json_request(opener, base_one+'/api/settings', 'PUT', {'providers':[provider]})
        project = json_request(opener, base_one+'/api/projects', 'POST', {'name':'P1 Process Test'})
        job = json_request(opener, base_one+f'/api/projects/{project["id"]}/jobs', 'POST', {
            'node_id':'p1-text','kind':'text','submission_id':'p1-process-job-001',
            'input':{'provider':'p1-fake','model':'p1-fake-model','prompt':'process isolation'},
        })
        assert job['status'] == 'queued'

        worker = subprocess.Popen(
            [sys.executable, '-m', 'backend.worker_cli', '--concurrency', '1'],
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_FLAGS,
        )
        processes.append(worker)
        deadline = time.time()+10
        while time.time()<deadline and not (data/'worker.lock').exists():
            time.sleep(.05)
        assert worker.poll() is None and (data/'worker.lock').exists()

        stop(web_one)
        assert worker.poll() is None, 'stopping Web must not stop Worker'
        restarted_web = web(web_one_port)
        assert restarted_web.pid != web_one.pid

        deadline = time.time()+15
        current = None
        while time.time()<deadline:
            current = json_request(opener, base_two+f'/api/jobs/{job["id"]}')
            if current['status'] == 'succeeded':
                break
            time.sleep(.1)
        assert current['status'] == 'succeeded'
        assert current['result']['text'] == 'P1 fake response'
        assert count_file.read_text(encoding='utf-8') == '1'

        contender = subprocess.run(
            [sys.executable, '-m', 'backend.worker_cli', '--concurrency', '1'],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', timeout=10, creationflags=CREATE_FLAGS,
        )
        assert contender.returncode == 2
        assert 'refused to start' in contender.stderr and '已有任务进程' in contender.stderr
        print(json.dumps({
            'web_pids':[web_one.pid,web_two.pid,restarted_web.pid],
            'worker_pid':worker.pid,'job_id':job['id'],'job_status':current['status'],
            'fake_request_count':1,'second_worker_exit':contender.returncode,
        }, ensure_ascii=False))
    finally:
        for process in reversed(processes):
            stop(process)
