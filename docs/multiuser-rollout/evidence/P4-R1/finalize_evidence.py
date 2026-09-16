"""Transform completed local logs into bounded shareable P4-R1 evidence.

python finalize_evidence.py FINAL_LOG_DIR DEVELOPMENT_LOG_DIR
Does not run tests or modify runtime; refuses unfinished/failed formal logs.
"""
import hashlib
import importlib.metadata
import json
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

out = Path(__file__).resolve().parent
source, development = map(Path, sys.argv[1:3])
sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
assert sha == 'e6c3edd95830d4c778fee357b8807d1443920a04'


def sanitize(value):
    # Preserve stdout/stderr except the exact machine user's home path.
    for prefix in (str(Path.home()), str(Path.home()).replace('\\', '/')):
        value = value.replace(prefix, '<LOCAL_USER>')
    return value


for name in ('backend-full.txt', 'targeted-green.txt', 'frontend-test-build.txt', 'routes-compile.txt'):
    raw = (source / name).read_text(encoding='utf-8-sig')
    assert 'UTC_END ' in raw, name
    assert not re.search(r'(?:EXIT_CODE|TEST_EXIT|BUILD_EXIT|COMPILE_EXIT|ROUTES_EXIT) [1-9]', raw), name
    (out / name).write_text(sanitize(raw), encoding='utf-8')
dev = (development / 'development-full.txt').read_text(encoding='utf-8-sig')
assert 'UTC_END ' in dev
(out / 'development-full.txt').write_text(sanitize(dev), encoding='utf-8')
backend = (out / 'backend-full.txt').read_text(encoding='utf-8')
passed = int(re.search(r'(\d+) passed', backend).group(1))
assert passed == 368 and 'EXIT_CODE 0' in backend
audit = json.loads((out / 'browser-db-audit.json').read_text(encoding='utf-8-sig'))
summary = {
    'status': 'READY_FOR_REVIEW', 'external_acceptance': 'pending', 'business_sha': sha,
    'base': 'c7d6a88a06a01035fd44e45309414c05e061ab64',
    'backend': {'passed': passed, 'exit_code': 0,
                'utc_start': re.search('UTC_START (.*)', backend).group(1),
                'utc_end': re.search('UTC_END (.*)', backend).group(1),
                'result': re.search(r'^.*368 passed.*$', backend, re.M).group(0)},
    'targeted': {'passed': 17, 'seconds': 43.87, 'exit_code': 0},
    'red': {'failed': 4, 'passed': 2, 'exit_code': 1, 'runtime_sha': 'c7d6a88a06a01035fd44e45309414c05e061ab64'},
    'frontend': {'passed': 128, 'failed': 0, 'skipped': 0, 'exit_code': 0, 'build_exit': 0, 'modules': 1827},
    'routes': {'registered': 99, 'api': 96, 'classified': 96, 'unclassified': 0, 'exit_code': 0},
    'compile_exit': 0,
    'browser': {'calls': 26, 'results': 26, 'observed_api_responses': 110,
                'checked_json': 99, 'unreadable_json': 9, 'unscanned_sse_responses': 2, 'canary_hits': 0,
                'database_tables': len(audit['table_scan']), 'database_rows': sum(v['rows'] for v in audit['table_scan']),
                'database_canary_hits': sum(v['canary_hits'] for v in audit['table_scan']),
                'logs': len(audit['log_scan']), 'log_hits': sum(v['canary_hit'] for v in audit['log_scan']),
                'fake_counts': audit['fake_counts'], 'exit_code': None},
    'not_run': ['real paid Provider', 'public deployment', 'large concurrency', 'new audio synthesis wire probe'],
    'warnings': ['websockets legacy/server deprecations', 'Vite chunk >500k'],
}
(out / 'SUMMARY.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
provenance = {'utc': datetime.now(timezone.utc).isoformat(), 'business_sha': sha,
              'platform': platform.platform(), 'python': platform.python_version(),
              'node': subprocess.check_output(['node', '--version'], text=True).strip(),
              'postgres': audit['postgres_version'],
              'packages': {v: importlib.metadata.version(v) for v in ('pytest', 'fastapi', 'httpx', 'psycopg', 'cryptography')},
              'browser': 'Codex in-app browser; kernel version unavailable',
              'privacy': 'Exact local home path removed from stdout/stderr; browser synthetic inputs precisely redacted',
              'runtime_after_business': subprocess.check_output(['git', 'diff', '--name-only', sha, '--', 'backend', 'src', 'tests', 'scripts'], text=True).strip()}
assert not provenance['runtime_after_business']
(out / 'provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
integrity = {'algorithm': 'SHA-256', 'normalization': 'CRLF -> LF for Git text blobs', 'business_sha': sha, 'files': [
    {'file': p.name, 'sha256': hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()}
    for p in sorted(out.iterdir()) if p.is_file() and p.name != 'integrity.json']}
(out / 'integrity.json').write_text(json.dumps(integrity, indent=2) + '\n', encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False))
