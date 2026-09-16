"""P1 lifecycle acceptance for the real Windows scripts and caller session."""
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

        second_worker = run('Start-Studio.ps1', data_b, '-WorkerOnly', expected=1)
        assert 'already has a Worker' in (second_worker['stdout'] + second_worker['stderr'])
        assert not (data_b/'worker.process.json').exists()
        original_worker_a = (data_a/'worker.process.json').read_bytes()
        tampered = read_record(data_a, 'worker')
        tampered['pid'] = restarted_web_a['pid']
        (data_a/'worker.process.json').write_text(
            json.dumps(tampered, ensure_ascii=False, indent=2), encoding='utf-8',
        )
        refused = run('Stop-Studio.ps1', data_a, '-WorkerOnly', expected=2)
        assert 'was not stopped' in (refused['stdout'] + refused['stderr'])
        assert process_alive(worker_a['pid'])
        assert process_alive(restarted_web_a['pid']), 'wrong PID must never be stopped'
        (data_a/'worker.process.json').write_bytes(original_worker_a)

        run('Stop-Studio.ps1', data_a)
        assert wait_stopped(restarted_web_a['pid'])
        assert wait_stopped(worker_a['pid'])
        print(json.dumps({
            'health': health_a,
            'initial_records': {'web': web_a, 'worker': worker_a},
            'restarted_web_record': restarted_web_a,
            'different_instance_refused': True,
            'different_data_dir_worker_refused': True,
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
    (destination/'dist'/'index.html').write_text('<!doctype html><title>P1-R3</title>', encoding='utf-8')


def powershell_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


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
               '-Port', port_b, '-NoBrowser', '-WebOnly')
        web_b = remember(data_b, 'web')
        assert web_a['instance_id'] != web_b['instance_id']
        assert web_b['project_root'].casefold() == str(project_b.resolve()).casefold()
        assert web_b['data_dir'].casefold() == str(data_b.resolve()).casefold()
        assert not (data_b/'worker.process.json').exists()

        invoke(project_b, 'Stop-Studio.ps1', data_value_b, stop_b_cwd, '-WebOnly')
        assert wait_stopped(web_b['pid'])
        assert process_alive(web_a['pid']) and process_alive(worker_a['pid'])
        for role in ('web', 'worker'):
            assert (data_a/f'{role}.process.json').read_bytes() == a_records_before[role]

        invoke(project_a, 'Stop-Studio.ps1', data_value_a, ordinary)
        assert wait_stopped(web_a['pid']) and wait_stopped(worker_a['pid'])
        print(json.dumps({
            'data_mode': data_mode,
            'project_a_records_unchanged_while_stopping_b': True,
            'project_a_pids': [web_a['pid'], worker_a['pid']],
            'project_b_pids': [web_b['pid']],
            'project_b_root': web_b['project_root'],
            'project_b_data': web_b['data_dir'],
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


@pytest.mark.skipif(os.name != 'nt', reason='PowerShell lifecycle is Windows-only')
@pytest.mark.parametrize('data_mode', ['unset', 'relative', 'absolute'])
def test_same_powershell_session_restores_caller_environment(tmp_path, data_mode):
    project_a, project_b = tmp_path/'project-a', tmp_path/'project-b'
    ordinary = tmp_path/'ordinary-cwd'
    copy_script_project(project_a)
    copy_script_project(project_b)
    ordinary.mkdir()

    if data_mode == 'unset':
        setup_environment = "Remove-Item Env:MVC_DATA_DIR,Env:PYTHONUTF8 -ErrorAction SilentlyContinue"
        data_a, data_b = project_a/'data', project_b/'data'
        exercise_cross_project = True
    elif data_mode == 'relative':
        setup_environment = "$env:MVC_DATA_DIR='relative-data'; $env:PYTHONUTF8='0'"
        data_a, data_b = project_a/'relative-data', project_b/'relative-data'
        exercise_cross_project = True
    else:
        absolute_data = tmp_path/'absolute-caller-data'
        setup_environment = (
            f"$env:MVC_DATA_DIR={powershell_literal(absolute_data)}; "
            "$env:PYTHONUTF8='0'"
        )
        data_a = data_b = absolute_data
        exercise_cross_project = False

    driver = tmp_path/f'same-session-{data_mode}.ps1'
    port = free_port()
    cross_project_block = ''
    if exercise_cross_project:
        cross_project_block = f"""
$startOutput=& $startB -WorkerOnly *>&1 | Out-String
Assert-CallerState 'start-b-success'
$trace.Add([pscustomobject]@{{Call='start-b-success';Pid=$PID;Output=$startOutput}})
$recordPathB={powershell_literal(data_b/'worker.process.json')}
if(-not (Test-Path -LiteralPath $recordPathB)){{throw 'B worker record was not created.'}}
$recordBytesBefore=[IO.File]::ReadAllBytes($recordPathB)
$workerRecord=Get-Content -LiteralPath $recordPathB -Raw | ConvertFrom-Json
$workerPid=[int]$workerRecord.pid

$stopAOutput=& $stopA -WorkerOnly *>&1 | Out-String
Assert-CallerState 'stop-a-after-start-b'
$trace.Add([pscustomobject]@{{Call='stop-a-after-start-b';Pid=$PID;Output=$stopAOutput}})
if($null -eq (Get-Process -Id $workerPid -ErrorAction SilentlyContinue)){{throw 'A stop terminated B worker.'}}
$recordBytesAfter=[IO.File]::ReadAllBytes($recordPathB)
if([Convert]::ToBase64String($recordBytesBefore) -cne [Convert]::ToBase64String($recordBytesAfter)){{
    throw 'A stop changed B worker record.'
}}

$stopBOutput=& $stopB -WorkerOnly *>&1 | Out-String
Assert-CallerState 'stop-b-success'
$trace.Add([pscustomobject]@{{Call='stop-b-success';Pid=$PID;Output=$stopBOutput}})
if($null -ne (Get-Process -Id $workerPid -ErrorAction SilentlyContinue)){{throw 'B worker did not stop.'}}
"""
    else:
        cross_project_block = """
$stopOutput=& $stopB -WorkerOnly *>&1 | Out-String
Assert-CallerState 'stop-b-absolute-success'
$trace.Add([pscustomobject]@{Call='stop-b-absolute-success';Pid=$PID;Output=$stopOutput})
"""

    driver.write_text(f"""
$ErrorActionPreference='Stop'
{setup_environment}
$projectA={powershell_literal(project_a)}
$projectB={powershell_literal(project_b)}
$startB=Join-Path $projectB 'Start-Studio.ps1'
$stopA=Join-Path $projectA 'Stop-Studio.ps1'
$stopB=Join-Path $projectB 'Stop-Studio.ps1'
$initialLocation=(Get-Location).Path

function Get-EnvironmentState([string]$Name){{
    $value=[Environment]::GetEnvironmentVariable($Name,[EnvironmentVariableTarget]::Process)
    return [pscustomobject]@{{Defined=$null -ne $value;Value=$value}}
}}

$initialMvc=Get-EnvironmentState 'MVC_DATA_DIR'
$initialPython=Get-EnvironmentState 'PYTHONUTF8'
$initialDatabase=Get-EnvironmentState 'OVC_DATABASE_URL'
$driverPid=$PID
$trace=[Collections.Generic.List[object]]::new()

function Assert-EnvironmentState($Expected,[string]$Name,[string]$Label){{
    $actual=Get-EnvironmentState $Name
    if($actual.Defined -ne $Expected.Defined){{throw "$Label changed whether $Name is defined."}}
    if($actual.Defined -and ([string]$actual.Value -cne [string]$Expected.Value)){{
        throw "$Label changed $Name from '$($Expected.Value)' to '$($actual.Value)'."
    }}
}}

function Assert-CallerState([string]$Label){{
    Assert-EnvironmentState $initialMvc 'MVC_DATA_DIR' $Label
    Assert-EnvironmentState $initialPython 'PYTHONUTF8' $Label
    Assert-EnvironmentState $initialDatabase 'OVC_DATABASE_URL' $Label
    if(-not [string]::Equals((Get-Location).Path,$initialLocation,[StringComparison]::OrdinalIgnoreCase)){{
        throw "$Label changed the caller working directory."
    }}
    if($PID -ne $driverPid){{throw "$Label ran in a different PowerShell process."}}
}}

$missingDist=Join-Path $projectB 'dist\\index.html'
Remove-Item -LiteralPath $missingDist -Force
$failed=$false
$failureMessage=''
try{{
    $failureOutput=& $startB -WebOnly -NoBrowser -Port {port} *>&1 | Out-String
}}catch{{
    $failed=$true
    $failureMessage=$_.Exception.Message
}}
if(-not $failed){{throw 'Expected Start-Studio to fail after applying its temporary environment.'}}
Assert-CallerState 'start-b-failure'
$trace.Add([pscustomobject]@{{Call='start-b-failure';Pid=$PID;Output=$failureOutput;Error=$failureMessage}})

{cross_project_block}

[pscustomobject]@{{
    DataMode={powershell_literal(data_mode)}
    DriverPid=$driverPid
    InitialMvc=$initialMvc
    InitialPython=$initialPython
    InitialDatabase=$initialDatabase
    FinalMvc=(Get-EnvironmentState 'MVC_DATA_DIR')
    FinalPython=(Get-EnvironmentState 'PYTHONUTF8')
    FinalDatabase=(Get-EnvironmentState 'OVC_DATABASE_URL')
    Location=(Get-Location).Path
    CrossProjectRecordUnchanged={'$true' if exercise_cross_project else '$false'}
    Trace=$trace
}} | ConvertTo-Json -Depth 6 -Compress
""", encoding='utf-8')

    env = {**os.environ, 'NO_PROXY': '127.0.0.1,localhost'}
    result = subprocess.run(
        [POWERSHELL, '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass',
         '-File', str(driver)],
        cwd=ordinary, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=CREATE_FLAGS, timeout=45,
    )
    stdout, stderr = decode_output(result.stdout), decode_output(result.stderr)
    try:
        assert result.returncode == 0, stdout + stderr
        payload = json.loads(stdout.strip().splitlines()[-1])
        assert payload['DriverPid']
        assert {entry['Pid'] for entry in payload['Trace']} == {payload['DriverPid']}
        assert payload['FinalMvc'] == payload['InitialMvc']
        assert payload['FinalPython'] == payload['InitialPython']
        assert payload['FinalDatabase'] == payload['InitialDatabase']
        assert payload['CrossProjectRecordUnchanged'] is exercise_cross_project
        print(json.dumps(payload, ensure_ascii=False))
    finally:
        record_path = data_b/'worker.process.json'
        if record_path.exists():
            try:
                pid = int(read_record(data_b, 'worker')['pid'])
                if process_alive(pid):
                    subprocess.run(
                        ['taskkill.exe', '/PID', str(pid), '/T', '/F'],
                        capture_output=True, creationflags=CREATE_FLAGS,
                    )
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                pass


@pytest.mark.skipif(os.name != 'nt', reason='PowerShell lifecycle is Windows-only')
def test_stop_nonzero_exit_restores_environment_and_location(tmp_path):
    project = tmp_path/'project'
    ordinary = tmp_path/'ordinary-cwd'
    data_dir = project/'relative-failure-data'
    copy_script_project(project)
    ordinary.mkdir()
    data_dir.mkdir()
    (data_dir/'worker.process.json').write_text('{not valid json', encoding='utf-8')

    snapshot_path = tmp_path/'nonzero-exit-snapshot.json'
    driver = tmp_path/'nonzero-exit-driver.ps1'
    driver.write_text(f"""
$ErrorActionPreference='Stop'
$env:MVC_DATA_DIR='relative-failure-data'
$env:PYTHONUTF8='0'
$initialLocation=(Get-Location).Path
$driverPid=$PID
$stopScript={powershell_literal(project/'Stop-Studio.ps1')}
$snapshotPath={powershell_literal(snapshot_path)}
try{{
    & $stopScript -WorkerOnly
    $stopExitCode=$LASTEXITCODE
}}finally{{
    [pscustomobject]@{{
        DriverPid=$driverPid
        FinallyPid=$PID
        Mvc=[Environment]::GetEnvironmentVariable('MVC_DATA_DIR',[EnvironmentVariableTarget]::Process)
        PythonUtf8=[Environment]::GetEnvironmentVariable('PYTHONUTF8',[EnvironmentVariableTarget]::Process)
        InitialLocation=$initialLocation
        FinalLocation=(Get-Location).Path
    }} | ConvertTo-Json -Compress | Set-Content -LiteralPath $snapshotPath -Encoding UTF8
}}
exit $stopExitCode
""", encoding='utf-8')

    result = subprocess.run(
        [POWERSHELL, '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass',
         '-File', str(driver)],
        cwd=ordinary, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=CREATE_FLAGS, timeout=30,
    )
    assert result.returncode == 2, decode_output(result.stdout) + decode_output(result.stderr)
    payload = json.loads(snapshot_path.read_text(encoding='utf-8-sig'))
    assert payload['DriverPid'] == payload['FinallyPid']
    assert payload['Mvc'] == 'relative-failure-data'
    assert payload['PythonUtf8'] == '0'
    assert payload['FinalLocation'].casefold() == payload['InitialLocation'].casefold()
    assert not (data_dir/'worker.process.json').exists()
    print(json.dumps(payload, ensure_ascii=False))
