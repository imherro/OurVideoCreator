"""Run the P5 verification commands against an explicit, unchanged business SHA.

Writes raw local logs to a new temporary directory, never publishes or declares
external acceptance. Review/redact these logs before copying them into docs.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ['backend', 'src', 'tests', 'scripts', 'migrations', 'package.json',
           'package-lock.json', 'tsconfig.json', 'vite.config.ts']


def utc():
    return datetime.now(timezone.utc).isoformat()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def check_business(sha):
    if git('rev-parse', 'HEAD') != sha:
        raise SystemExit('HEAD no longer matches the requested business SHA')
    if git('status', '--porcelain', '--', *RUNTIME):
        raise SystemExit('Runtime/test sources must be committed before formal capture')


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python scripts/capture_p5_evidence.py BUSINESS_SHA')
    sha = sys.argv[1]
    check_business(sha)
    out = Path(tempfile.mkdtemp(prefix='ovc-p5-evidence-'))
    commands = [
        ('backend-full', [sys.executable, '-m', 'pytest', '-q', '--tb=short']),
        ('concurrency-traces', [sys.executable, '-m', 'pytest', '-q', '-s', '--tb=short',
            'tests/test_p5_object_transactions.py::test_same_revision_real_pg_waiters_one_commit_one_conflict',
            'tests/test_p5_object_transactions.py::test_locked_shot_does_not_lock_other_shot',
            'tests/test_p5_object_transactions.py::test_timeline_lease_expiry_takeover_old_token_and_locked_clock',
            'tests/test_p5_owned_content.py::test_same_version_wait_chain_one_success_one_conflict',
            'tests/test_p5_relation_candidates.py::test_two_candidates_same_revision_pg_waiters_only_one_adoption',
            'tests/test_p5_storyboard_candidates.py::test_two_storyboard_candidates_compete_through_real_pg_graph_lock',
            'tests/test_p5_run_permissions.py::test_two_real_pg_waiting_runs_preserve_independent_batch_receipts',
            'tests/test_p5_collaboration_actions.py::test_capture_rechecks_director_after_real_pg_wait',
            'tests/test_p5_resume_permissions.py::test_resume_rechecks_after_real_pg_object_lock_wait']),
        ('frontend', ['npm.cmd', 'test']),
        ('typescript', ['npx.cmd', 'tsc', '--noEmit']),
        ('build', ['npm.cmd', 'run', 'build']),
        ('routes', [sys.executable, 'scripts/audit_routes.py']),
        ('compile', [sys.executable, '-m', 'compileall', '-q', 'backend', 'tests']),
        ('diff-check', ['git', '-c', 'core.safecrlf=false', 'diff', '--check']),
    ]
    manifest = {'business_sha': sha, 'repository': git('remote', 'get-url', 'origin'),
                'utc_start': utc(), 'directory': str(out), 'runs': [],
                'external_acceptance': 'not_requested_by_this_script'}
    print(json.dumps(manifest), flush=True)
    for name, command in commands:
        check_business(sha)
        record = {'name': name, 'command': subprocess.list2cmdline(command), 'utc_start': utc()}
        started = time.perf_counter()
        with (out / f'{name}.txt').open('w', encoding='utf-8') as log:
            log.write(f'BUSINESS_SHA {sha}\nUTC_START {record["utc_start"]}\nCOMMAND {record["command"]}\n')
            log.flush()
            process = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                     env={**os.environ, 'PYTHONUTF8': '1'})
            record.update(exit_code=process.returncode, utc_end=utc(), seconds=time.perf_counter()-started)
            log.write(f'\nEXIT_CODE {process.returncode}\nUTC_END {record["utc_end"]}\n')
        check_business(sha)
        manifest['runs'].append(record)
        (out / 'runs.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print(json.dumps(record), flush=True)
    manifest['utc_end'] = utc()
    (out / 'runs.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return int(any(row['exit_code'] != 0 for row in manifest['runs']))


if __name__ == '__main__':
    raise SystemExit(main())
