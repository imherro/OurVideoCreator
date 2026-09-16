"""Command-line entry point for the independent P1 Worker process."""
from __future__ import annotations

import argparse
import signal
import sys
import threading

from . import store
from .instance_identity import describe as describe_instance
from .worker import Worker


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description='Run the OurVideoCreator task Worker')
    value.add_argument('--concurrency', type=int, default=4, help='Worker threads inside this single process')
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    store.init()
    worker = Worker(concurrency=args.concurrency)
    stopping = threading.Event()

    def request_stop(_signum=None, _frame=None):
        stopping.set()

    for name in ('SIGINT', 'SIGTERM', 'SIGBREAK'):
        found = getattr(signal, name, None)
        if found is not None:
            signal.signal(found, request_stop)
    try:
        worker.start()
    except RuntimeError as exc:
        print(f'Worker refused to start: {exc}', file=sys.stderr, flush=True)
        return 2
    print(
        f'Worker started: instance={describe_instance()["instance_id"]} data={store.DATA} '
        f'concurrency={worker.concurrency} mode=single-process',
        flush=True,
    )
    try:
        while not stopping.wait(0.5):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        worker.stop()
    print('Worker stopped', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
