"""P1-R1 acceptance for the real Windows lifecycle scripts."""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

import pytest


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = 'powershell.exe'
CREATE_FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def process_alive(pid):
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


def wait_stopped(pid, timeout=8):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not process_alive(pid):
            return True
        time.sleep(0.1)
    return not process_alive(pid)


def read_record(data_dir, role):
    return json.loads((data_dir/f'{role}.process.json').read_text(encoding='utf-8-sig'))


def decode_output(value):
    for encoding in ('utf-8', 'gb18030'):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            pass
    return value.decode('utf-8', errors='replace')


@pytest.mark.skipif(os.name != 'nt', reason='PowerShell lifecycle is Windows-only')
def test_powershell_scripts_own_only_their_instance(tmp_path):
    if not (ROOT/'dist'/'index.html').exists():
        pytest.skip('front-end dist is required by the real Start-Studio script')
    data_a, data_b = tmp_path/'instance-a', tmp_path/'instance-b'
    data_a.mkdir()
    data_b.mkdir()
    port = free_port()
    owned_pids = set()
    transcript = []

    def run(script, data_dir, *arguments, expected=0):
        env = {
            **os.environ,
            'MVC_DATA_DIR': str(data_dir),
            'PYTHONUTF8': '1',
            'NO_PROXY': '127.0.0.1,localhost',
        }
        command = [
            POWERSHELL, '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', str(ROOT/script), *map(str, arguments),
        ]
        invocation = len(transcript) + 1
        stdout_path = tmp_path/f'powershell-{invocation}.stdout.log'
        stderr_path = tmp_path/f'powershell-{invocation}.stderr.log'
        with stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
            result = subprocess.run(
                command, cwd=ROOT, env=env, stdout=stdout, stderr=stderr,
                creationflags=CREATE_FLAGS, timeout=30,
            )
        entry = {
            'script': script,
            'data_dir': data_dir.name,
            'arguments': list(map(str, arguments)),
            'returncode': result.returncode,
            'stdout': decode_output(stdout_path.read_bytes()),
            'stderr': decode_output(stderr_path.read_bytes()),
        }
        transcript.append(entry)
        assert result.returncode == expected, json.dumps(entry, ensure_ascii=False)
        return entry

    def remember(data_dir, role):
        record = read_record(data_dir, role)
        owned_pids.add(int(record['pid']))
        return record

    try:
        run('Start-Studio.ps1', data_a, '-Port', port, '-NoBrowser')
        web_a = remember(data_a, 'web')
        worker_a = remember(data_a, 'worker')
        with urlopen(f'http://127.0.0.1:{port}/api/health', timeout=3) as response:
            health_a = json.loads(response.read())
        assert health_a['instance_id'] == web_a['instance_id'] == worker_a['instance_id']
        assert web_a['project_root'] == worker_a['project_root']
        assert web_a['data_dir'] == worker_a['data_dir']

        run('Start-Studio.ps1', data_a, '-Port', port, '-NoBrowser')
        assert read_record(data_a, 'web')['pid'] == web_a['pid']
        assert read_record(data_a, 'worker')['pid'] == worker_a['pid']

        run('Stop-Studio.ps1', data_a, '-WebOnly')
        assert wait_stopped(web_a['pid'])
        assert process_alive(worker_a['pid']), 'WebOnly must leave Worker running'
        assert not (data_a/'web.process.json').exists()
        assert (data_a/'worker.process.json').exists()

        run('Start-Studio.ps1', data_a, '-Port', port, '-NoBrowser', '-WebOnly')
        restarted_web_a = remember(data_a, 'web')
        assert restarted_web_a['pid'] != web_a['pid']
        assert read_record(data_a, 'worker')['pid'] == worker_a['pid']

        collision = run(
            'Start-Studio.ps1', data_b, '-Port', port, '-NoBrowser',
            expected=1,
        )
        assert 'different studio instance' in (collision['stdout'] + collision['stderr'])
        assert not (data_b/'web.process.json').exists()
        assert not (data_b/'worker.process.json').exists()
        assert process_alive(restarted_web_a['pid']) and process_alive(worker_a['pid'])

        run('Start-Studio.ps1', data_b, '-WorkerOnly')
        worker_b = remember(data_b, 'worker')
        original_worker_a = (data_a/'worker.process.json').read_bytes()
        tampered = read_record(data_a, 'worker')
        tampered['pid'] = worker_b['pid']
        (data_a/'worker.process.json').write_text(
            json.dumps(tampered, ensure_ascii=False, indent=2), encoding='utf-8',
        )
        refused = run('Stop-Studio.ps1', data_a, '-WorkerOnly', expected=2)
        assert 'was not stopped' in (refused['stdout'] + refused['stderr'])
        assert process_alive(worker_a['pid'])
        assert process_alive(worker_b['pid']), 'wrong PID must never be stopped'
        (data_a/'worker.process.json').write_bytes(original_worker_a)

        run('Stop-Studio.ps1', data_b, '-WorkerOnly')
        assert wait_stopped(worker_b['pid'])
        run('Stop-Studio.ps1', data_a)
        assert wait_stopped(restarted_web_a['pid'])
        assert wait_stopped(worker_a['pid'])
        print(json.dumps({
            'health': health_a,
            'initial_records': {'web': web_a, 'worker': worker_a},
            'restarted_web_record': restarted_web_a,
            'different_instance_refused': True,
            'wrong_pid_refused': True,
            'web_only_preserved_worker_pid': worker_a['pid'],
            'transcript': transcript,
        }, ensure_ascii=False))
    finally:
        for data_dir in (data_a, data_b):
            try:
                run('Stop-Studio.ps1', data_dir)
            except Exception:
                pass
        for pid in owned_pids:
            if process_alive(pid):
                subprocess.run(
                    ['taskkill.exe', '/PID', str(pid), '/T', '/F'],
                    capture_output=True, creationflags=CREATE_FLAGS,
                )


def copy_script_project(destination):
    destination.mkdir()
    shutil.copytree(
        ROOT/'backend', destination/'backend',
        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'),
    )
    for name in ('Studio-Process.ps1', 'Start-Studio.ps1', 'Stop-Studio.ps1'):
        shutil.copy2(ROOT/name, destination/name)
    (destination/'dist').mkdir()
    (destination/'dist'/'index.html').write_text('<!doctype html><title>P1-R2</title>', encoding='utf-8')


@pytest.mark.skipif(os.name != 'nt', reason='PowerShell lifecycle is Windows-only')
@pytest.mark.parametrize('data_mode', ['unset', 'absolute', 'relative'])
def test_absolute_script_path_targets_its_own_project_from_any_cwd(tmp_path, data_mode):
    project_a, project_b = tmp_path/'project-a', tmp_path/'project-b'
    ordinary = tmp_path/'ordinary-cwd'
    copy_script_project(project_a)
    copy_script_project(project_b)
    ordinary.mkdir()
    owned_pids = set()
    transcript = []

    if data_mode == 'unset':
        data_value_a = data_value_b = None
        data_a, data_b = project_a/'data', project_b/'data'
        start_a_cwd, start_b_cwd, stop_b_cwd = project_a, ordinary, project_a
    elif data_mode == 'absolute':
        data_a, data_b = tmp_path/'absolute-a', tmp_path/'absolute-b'
        data_value_a, data_value_b = str(data_a), str(data_b)
        start_a_cwd, start_b_cwd, stop_b_cwd = ordinary, project_a, project_b
    else:
        data_value_a = data_value_b = 'relative-data'
        data_a, data_b = project_a/'relative-data', project_b/'relative-data'
        start_a_cwd, start_b_cwd, stop_b_cwd = project_b, project_b, project_a

    def invoke(project_root, script, data_value, cwd, *arguments, expected=0):
        env = {
            **os.environ,
            'PYTHONUTF8': '1',
            'NO_PROXY': '127.0.0.1,localhost',
        }
        if data_value is None:
            env.pop('MVC_DATA_DIR', None)
        else:
            env['MVC_DATA_DIR'] = data_value
        invocation = len(transcript) + 1
        stdout_path = tmp_path/f'{data_mode}-{invocation}.stdout.log'
        stderr_path = tmp_path/f'{data_mode}-{invocation}.stderr.log'
        command = [
            POWERSHELL, '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', str((project_root/script).resolve()), *map(str, arguments),
        ]
        with stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
            result = subprocess.run(
                command, cwd=cwd, env=env, stdout=stdout, stderr=stderr,
                creationflags=CREATE_FLAGS, timeout=30,
            )
        entry = {
            'project': project_root.name,
            'script': script,
            'cwd': str(cwd),
            'data_value': data_value,
            'arguments': list(map(str, arguments)),
            'returncode': result.returncode,
            'stdout': decode_output(stdout_path.read_bytes()),
            'stderr': decode_output(stderr_path.read_bytes()),
        }
        transcript.append(entry)
        assert result.returncode == expected, json.dumps(entry, ensure_ascii=False)
        return entry

    def remember(data_dir, role):
        record = read_record(data_dir, role)
        owned_pids.add(int(record['pid']))
        return record

    port_a, port_b = free_port(), free_port()
    try:
        invoke(project_a, 'Start-Studio.ps1', data_value_a, start_a_cwd,
               '-Port', port_a, '-NoBrowser')
        web_a, worker_a = remember(data_a, 'web'), remember(data_a, 'worker')
        a_records_before = {
            role: (data_a/f'{role}.process.json').read_bytes()
            for role in ('web', 'worker')
        }

        invoke(project_b, 'Start-Studio.ps1', data_value_b, start_b_cwd,
               '-Port', port_b, '-NoBrowser')
        web_b, worker_b = remember(data_b, 'web'), remember(data_b, 'worker')
        assert web_a['instance_id'] != web_b['instance_id']
        assert worker_a['instance_id'] != worker_b['instance_id']
        assert web_b['project_root'].casefold() == str(project_b.resolve()).casefold()
        assert worker_b['data_dir'].casefold() == str(data_b.resolve()).casefold()

        invoke(project_b, 'Stop-Studio.ps1', data_value_b, stop_b_cwd)
        assert wait_stopped(web_b['pid']) and wait_stopped(worker_b['pid'])
        assert process_alive(web_a['pid']) and process_alive(worker_a['pid'])
        for role in ('web', 'worker'):
            assert (data_a/f'{role}.process.json').read_bytes() == a_records_before[role]

        invoke(project_a, 'Stop-Studio.ps1', data_value_a, ordinary)
        assert wait_stopped(web_a['pid']) and wait_stopped(worker_a['pid'])
        print(json.dumps({
            'data_mode': data_mode,
            'project_a_records_unchanged_while_stopping_b': True,
            'project_a_pids': [web_a['pid'], worker_a['pid']],
            'project_b_pids': [web_b['pid'], worker_b['pid']],
            'project_b_root': web_b['project_root'],
            'project_b_data': worker_b['data_dir'],
            'transcript': transcript,
        }, ensure_ascii=False))
    finally:
        for project_root, data_value, cwd in (
            (project_b, data_value_b, ordinary),
            (project_a, data_value_a, ordinary),
        ):
            try:
                invoke(project_root, 'Stop-Studio.ps1', data_value, cwd)
            except Exception:
                pass
        for pid in owned_pids:
            if process_alive(pid):
                subprocess.run(
                    ['taskkill.exe', '/PID', str(pid), '/T', '/F'],
                    capture_output=True, creationflags=CREATE_FLAGS,
                )
