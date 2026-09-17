"""DEFERRED P6 real-process baseline: two workers may share one isolated PG queue.

The full fault/quota matrix is added as implementation proceeds. This first
regression must fail on P5's database-wide exclusion, not on a simulated lock.
"""
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_two_independent_workers_can_start_on_same_queue(tmp_path):
    workers = []
    logs = []
    try:
        for index in range(2):
            path = tmp_path / f'worker-{index}.log'
            stream = path.open('w', encoding='utf-8')
            logs.append(stream)
            process = subprocess.Popen(
                [sys.executable, '-u', '-m', 'backend.worker_cli', '--concurrency', '1'],
                cwd=ROOT, env={**os.environ, 'MVC_DATA_DIR': str(tmp_path / f'media-{index}')},
                stdout=stream, stderr=subprocess.STDOUT,
            )
            workers.append(process)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                body = path.read_text(encoding='utf-8')
                if process.poll() is not None or 'Worker started:' in body:
                    break
                time.sleep(.05)
            body = path.read_text(encoding='utf-8')
            print(f'worker-{index} pid={process.pid} exit={process.poll()} log={body}')
            assert process.poll() is None, body
            assert 'Worker started:' in body, body
        assert workers[0].pid != workers[1].pid
        assert all(process.poll() is None for process in workers)
    finally:
        # Only exact Popen handles owned by this test; never scan/kill services.
        for process in workers:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=15)
        for stream in logs:
            stream.close()
