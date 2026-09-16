"""Stable local identity for one project-root/data-directory deployment."""
from __future__ import annotations

import hashlib
import json
import os

from . import store
from .database import safe_database_identity


def _canonical(path) -> str:
    return os.path.normcase(str(path.resolve()))


def describe() -> dict[str, str | int]:
    project_root = _canonical(store.ROOT)
    data_dir = _canonical(store.DATA)
    database_identity = safe_database_identity()
    digest = hashlib.sha256(
        f'{project_root}\0{data_dir}\0{database_identity}'.encode('utf-8')
    ).hexdigest()
    return {
        'schema': 1,
        'instance_id': f'ovc-{digest[:32]}',
        'project_root': project_root,
        'data_dir': data_dir,
        'database': database_identity,
    }


def main() -> int:
    print(json.dumps(describe(), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
