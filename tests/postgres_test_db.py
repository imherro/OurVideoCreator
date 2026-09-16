"""Create and destroy only explicitly named, isolated PostgreSQL test DBs."""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url


ADMIN_ENV = 'OVC_TEST_ADMIN_URL'
ALLOWED_PREFIX = 'ovc_test_'
ALLOWED_NAME = re.compile(r'^ovc_test_[a-z0-9_]{8,80}$')


def _admin_url():
    value = os.environ.get(ADMIN_ENV, '').strip()
    if not value:
        raise RuntimeError(
            f'{ADMIN_ENV} is required for tests; it must point to a PostgreSQL admin database.'
        )
    parsed = make_url(value)
    if parsed.drivername not in {'postgresql', 'postgresql+psycopg'}:
        raise RuntimeError(f'{ADMIN_ENV} must be PostgreSQL; SQLite tests are retired.')
    return parsed


def _dsn(url) -> str:
    return url.set(drivername='postgresql').render_as_string(hide_password=False)


def _assert_safe_target(database_name: str) -> None:
    if not ALLOWED_NAME.fullmatch(database_name):
        raise RuntimeError(
            f'Refusing test database operation for {database_name!r}; '
            f'target must match {ALLOWED_NAME.pattern!r}.'
        )


def create_isolated_database(root: Path) -> tuple[str, str]:
    admin = _admin_url()
    name = f'{ALLOWED_PREFIX}{os.getpid()}_{uuid.uuid4().hex[:12]}'.lower()
    _assert_safe_target(name)
    with psycopg.connect(_dsn(admin), autocommit=True) as connection:
        connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    target = admin.set(database=name, drivername='postgresql+psycopg')
    target_url = target.render_as_string(hide_password=False)
    os.environ['OVC_DATABASE_URL'] = target_url
    config = Config(str(root / 'alembic.ini'))
    command.upgrade(config, 'head')
    return name, target_url


def drop_isolated_database(name: str, target_url: str) -> None:
    _assert_safe_target(name)
    configured = make_url(os.environ.get('OVC_DATABASE_URL', ''))
    if configured.database != name or configured.render_as_string(hide_password=False) != target_url:
        raise RuntimeError('Refusing to drop a test database that is not the active isolated target.')
    admin = _admin_url()
    with psycopg.connect(_dsn(admin), autocommit=True) as connection:
        connection.execute(
            'SELECT pg_terminate_backend(pid) FROM pg_stat_activity '
            'WHERE datname=%s AND pid<>pg_backend_pid()',
            (name,),
        )
        connection.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
