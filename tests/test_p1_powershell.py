"""P1-R1 acceptance for the real Windows lifecycle scripts."""
from __future__ import annotations

import ctypes
import json
import os
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
