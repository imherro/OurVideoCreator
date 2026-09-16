"""Fixed-SHA affected rerun after the frontend-only Twick correction."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'scripts'))
from capture_p5_evidence import check_business, git, utc

SHA = '0851dce02e0f22e87f6247b029fd3faedd39e7dd'
BASE = 'f4773f0075325625c6cf2e6236c5d2014d416d3f'
out = Path(__file__).parent / 'commands-0851dce'
out.mkdir(exist_ok=False)
check_business(SHA)
unchanged = ['backend', 'migrations', 'scripts', 'package.json', 'package-lock.json']
assert not git('diff', BASE, SHA, '--', *unchanged), 'backend or dependency baseline changed'
manifest = {'business_sha': SHA, 'backend_baseline_sha': BASE, 'utc_start': utc(),
    'identical_paths': unchanged, 'changed_paths': git('diff', '--name-only', BASE, SHA).splitlines(), 'runs': []}
commands = [
    ('frontend', ['npm.cmd', 'test']),
    ('typescript', ['npx.cmd', 'tsc', '--noEmit']),
    ('build', ['npm.cmd', 'run', 'build']),
    ('editor-renderer', [sys.executable, '-m', 'pytest', '-q', '--tb=short', 'tests/test_editor_renderer.py']),
    ('diff-check', ['git', '-c', 'core.safecrlf=false', 'diff', '--check']),
]
for name, command in commands:
    check_business(SHA)
    record = {'name': name, 'command': subprocess.list2cmdline(command), 'utc_start': utc()}
    started = time.perf_counter()
    with (out / f'{name}.txt').open('w', encoding='utf-8') as log:
        log.write(f'BUSINESS_SHA {SHA}\nUTC_START {record["utc_start"]}\nCOMMAND {record["command"]}\n')
        log.flush()
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
            env={**os.environ, 'PYTHONUTF8': '1'})
        record.update(exit_code=result.returncode, utc_end=utc(), seconds=time.perf_counter()-started)
        log.write(f'\nEXIT_CODE {result.returncode}\nUTC_END {record["utc_end"]}\n')
    check_business(SHA)
    manifest['runs'].append(record)
    (out / 'runs.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(record), flush=True)
manifest['utc_end'] = utc()
(out / 'runs.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
raise SystemExit(int(any(r['exit_code'] for r in manifest['runs'])))
