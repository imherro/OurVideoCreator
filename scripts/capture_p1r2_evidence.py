"""Run P1-R2 acceptance commands and retain their combined, unedited output."""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'docs'/'multiuser-rollout'/'evidence'/'P1-R2'

COMMANDS = [
    ('01-npm-ci', ['npm.cmd', 'ci']),
    ('02-npm-test', ['npm.cmd', 'test']),
    ('03-npm-build', ['npm.cmd', 'run', 'build']),
    ('04-pytest-collect', [sys.executable, '-m', 'pytest', '--collect-only', '-q']),
    ('05-pytest', [sys.executable, '-m', 'pytest', '-q']),
    ('06-cross-root-powershell', [
        sys.executable, '-m', 'pytest', '-q',
        'tests/test_p1_powershell.py::test_absolute_script_path_targets_its_own_project_from_any_cwd',
        '-s',
    ]),
    ('07-all-powershell-lifecycle', [
        sys.executable, '-m', 'pytest', '-q', 'tests/test_p1_powershell.py', '-s',
    ]),
    ('08-inflight-web-restart', [
        sys.executable, '-m', 'pytest', '-q', 'tests/test_p1_processes.py', '-s',
    ]),
    ('09-ffmpeg-export', [
        sys.executable, '-m', 'pytest', '-q', 'tests/test_export.py', '-s',
    ]),
    ('10-zero-upstream-on-missing-provider', [
        sys.executable, '-m', 'pytest', '-q',
        'tests/test_api.py::test_missing_or_removed_local_provider_fails_before_any_upstream_request',
        '-s',
    ]),
    ('11-route-audit', [sys.executable, 'scripts/audit_routes.py']),
    ('12-diff-check', ['git', 'diff', '--check']),
]


def command_text(command):
    return subprocess.list2cmdline(command)


def checked_output(command):
    return subprocess.run(
        command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='replace', check=True,
    ).stdout.strip()


def run(name, command):
    started = datetime.now(timezone.utc)
    begin = time.perf_counter()
    process = subprocess.run(
        command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='replace',
        env={**os.environ, 'PYTHONUTF8': '1'},
    )
    metadata = {
        'name': name,
        'command': command_text(command),
        'started_utc': started.isoformat(),
        'duration_seconds': round(time.perf_counter() - begin, 3),
        'exit_code': process.returncode,
        'log': f'{name}.log',
    }
    (OUT/metadata['log']).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + '\n\n' + process.stdout,
        encoding='utf-8',
    )
    return metadata


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    head = checked_output(['git', 'rev-parse', 'HEAD'])
    if checked_output(['git', 'status', '--porcelain']):
        raise SystemExit('P1-R2 evidence must be captured from a clean business-code commit.')
    tracked_removed = checked_output([
        'git', 'ls-files', 'inference', 'backend/runtime.py',
        'scripts/import_local_engine.py', 'scripts/smoke_local.py',
    ])
    surface = {
        'embedded_inference_directory_exists': (ROOT/'inference').exists(),
        'runtime_module_exists': (ROOT/'backend'/'runtime.py').exists(),
        'tracked_removed_paths': tracked_removed.splitlines() if tracked_removed else [],
        'expected': 'all false/empty',
    }
    (OUT/'13-removed-surface.json').write_text(
        json.dumps(surface, ensure_ascii=False, indent=2) + '\n', encoding='utf-8',
    )
    summary = {
        'evidence_kind': 'P1-R2 final acceptance run',
        'business_code_sha': head,
        'capture_start_head': head,
        'capture_started_utc': datetime.now(timezone.utc).isoformat(),
        'repository': 'https://github.com/imherro/OurVideoCreator',
        'supersedes': 'P1-R1 failed review at e698dcb2167cccd6c4797a49f2e4b1581b6c2b95 without overwriting earlier evidence',
        'environment': {
            'platform': platform.platform(),
            'python': sys.version,
            'node': checked_output(['node', '--version']),
            'npm': checked_output(['npm.cmd', '--version']),
        },
        'test_isolation': 'PowerShell cross-root tests use two disposable project copies, isolated data directories, loopback-only ports, and only their recorded test PIDs',
        'paid_egress_guard': 'pytest blocks non-loopback sockets; fake Providers are loopback-only; no real credentials are supplied',
        'removed_surface': surface,
        'runs': [],
    }
    for name, command in COMMANDS:
        summary['runs'].append(run(name, command))
    summary['capture_finished_utc'] = datetime.now(timezone.utc).isoformat()
    (OUT/'SUMMARY.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8',
    )
    return 0 if all(item['exit_code'] == 0 for item in summary['runs']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
