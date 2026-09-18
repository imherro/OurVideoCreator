"""PostgreSQL configuration, connections, and schema-readiness checks.

Runtime code deliberately does not create or alter schema.  Operators apply
the standalone Alembic migration before starting Web or Worker processes.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import set_json_loads
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url


DATABASE_ENV = 'OVC_DATABASE_URL'
SCHEMA_REVISION = '0009_episode_deliveries'


class DatabaseConfigurationError(RuntimeError):
    """Raised when PostgreSQL configuration is absent or unsafe."""


class DatabaseNotReadyError(RuntimeError):
    """Raised when PostgreSQL is reachable but the schema is not at head."""


def database_url() -> str:
    value = os.environ.get(DATABASE_ENV, '').strip()
    if not value:
        raise DatabaseConfigurationError(
            f'{DATABASE_ENV} is required; configure a PostgreSQL DSN before starting the studio.'
        )
    try:
        parsed = make_url(value)
    except Exception as exc:
        raise DatabaseConfigurationError(f'{DATABASE_ENV} is not a valid database URL.') from exc
    if parsed.drivername not in {'postgresql', 'postgresql+psycopg'}:
        raise DatabaseConfigurationError(
            f'{DATABASE_ENV} must use PostgreSQL (postgresql+psycopg); SQLite fallback is disabled.'
        )
    if not parsed.database:
        raise DatabaseConfigurationError(f'{DATABASE_ENV} must name a PostgreSQL database.')
    if parsed.drivername == 'postgresql':
        return parsed.set(drivername='postgresql+psycopg').render_as_string(hide_password=False)
    return value


def psycopg_dsn() -> str:
    """Return a libpq-compatible DSN without exposing it in diagnostics."""
    parsed = make_url(database_url()).set(drivername='postgresql')
    return parsed.render_as_string(hide_password=False)


def safe_database_identity() -> str:
    """Stable database identity that never contains credentials."""
    parsed = make_url(database_url())
    host = parsed.host or 'localhost'
    port = parsed.port or 5432
    return f'postgresql://{host}:{port}/{parsed.database}'


def redact_database_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except Exception:
        return '<invalid database URL>'
    host = parsed.hostname or ''
    if parsed.port:
        host = f'{host}:{parsed.port}'
    if parsed.username:
        host = f'{parsed.username}:***@{host}'
    return urlunsplit((parsed.scheme, host, parsed.path, '', ''))


@lru_cache(maxsize=4)
def _engine_for(url: str) -> Engine:
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=300,
        future=True,
        hide_parameters=True,
    )


def engine() -> Engine:
    return _engine_for(database_url())


def dispose_engines() -> None:
    """Test/lifecycle helper for processes that deliberately change DSNs."""
    # Cached engines are process-local. The active engine is the only one used
    # by normal runtime; dispose it before clearing the URL-keyed cache.
    try:
        engine().dispose()
    except DatabaseConfigurationError:
        pass
    _engine_for.cache_clear()


def _raw_json(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode('utf-8')
    return value


def connect() -> psycopg.Connection:
    try:
        connection = psycopg.connect(
            psycopg_dsn(),
            row_factory=dict_row,
            connect_timeout=5,
            application_name='our-video-creator',
        )
    except (psycopg.Error, OSError) as exc:
        raise DatabaseConfigurationError(
            f'PostgreSQL is unavailable at {redact_database_url(database_url())}: {exc.__class__.__name__}'
        ) from exc
    # Keep the existing serialization boundary stable while JSONB is used on
    # disk.  Business code explicitly parses/serializes JSON at the API edge.
    set_json_loads(_raw_json, connection)
    return connection


@contextmanager
def transaction():
    connection = connect()
    try:
        with connection.transaction():
            yield connection
    finally:
        connection.close()


def check_ready() -> dict[str, object]:
    """Verify connectivity and the exact Alembic head, without migrating."""
    try:
        with engine().connect() as connection:
            dialect = connection.dialect.name
            if dialect != 'postgresql':
                raise DatabaseConfigurationError('Runtime database dialect must be PostgreSQL.')
            try:
                revision = connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
            except Exception as exc:
                raise DatabaseNotReadyError(
                    'PostgreSQL schema is not initialized; run `python -m alembic upgrade head`.'
                ) from exc
            if revision != SCHEMA_REVISION:
                raise DatabaseNotReadyError(
                    f'PostgreSQL schema revision {revision!r} does not match required {SCHEMA_REVISION!r}; '
                    'run `python -m alembic upgrade head`.'
                )
            row = connection.execute(text(
                "SELECT current_setting('server_version') AS server_version, "
                'current_database() AS database_name, current_schema() AS schema_name, '
                'pg_backend_pid() AS pg_backend_pid'
            )).mappings().one()
            return dict(row)
    except (DatabaseConfigurationError, DatabaseNotReadyError):
        raise
    except Exception as exc:
        raise DatabaseConfigurationError(
            f'PostgreSQL readiness check failed at {redact_database_url(database_url())}: '
            f'{exc.__class__.__name__}'
        ) from exc


def worker_lock_connection() -> psycopg.Connection:
    """Return a dedicated session for the single-Worker advisory lock."""
    return connect()


class WorkerAdvisoryLock:
    """One session-level lock for the actual PostgreSQL queue database."""

    # Fixed application namespace. PostgreSQL already scopes advisory locks by
    # database, so every process claiming this queue competes on the same key.
    KEY = 0x4F56435F574B5231  # "OVC_WKR1"
    KEY_HIGH = KEY >> 32
    KEY_LOW = KEY & 0xFFFFFFFF

    def __init__(self):
        self.connection: psycopg.Connection | None = None
        self.backend_pid: int | None = None
        self._mutex = threading.Lock()

    def acquire(self) -> None:
        if self.connection is not None:
            raise RuntimeError('Worker PostgreSQL advisory lock is already held.')
        connection = worker_lock_connection()
        connection.autocommit = True
        try:
            acquired = connection.execute(
                'SELECT pg_try_advisory_lock(%s) AS acquired', (self.KEY,)
            ).fetchone()['acquired']
            if not acquired:
                raise RuntimeError(
                    'This PostgreSQL queue already has a Worker; the second Worker was refused.'
                )
        except BaseException:
            connection.close()
            raise
        self.connection = connection
        self.backend_pid = connection.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid']

    def assert_held(self) -> None:
        """Fail if the dedicated PostgreSQL session no longer owns its lock.

        This deliberately never reacquires the lock: losing the session is a
        fatal ownership failure and the Worker process must be restarted.
        """
        with self._mutex:
            connection = self.connection
            if connection is None:
                raise RuntimeError('Worker PostgreSQL advisory lock is not held.')
            try:
                row = connection.execute(
                    """SELECT pg_backend_pid() AS pid, EXISTS(
                        SELECT 1 FROM pg_locks
                        WHERE locktype='advisory' AND pid=pg_backend_pid()
                        AND classid=%s AND objid=%s AND objsubid=1 AND granted
                    ) AS held""",
                    (self.KEY_HIGH, self.KEY_LOW),
                ).fetchone()
            except BaseException as exc:
                raise RuntimeError('Worker lost its PostgreSQL advisory-lock session.') from exc
            if not row['held'] or row['pid'] != self.backend_pid:
                raise RuntimeError('Worker no longer owns its PostgreSQL advisory lock.')

    def release(self) -> None:
        with self._mutex:
            connection, self.connection = self.connection, None
            self.backend_pid = None
            if connection is None:
                return
            try:
                connection.execute('SELECT pg_advisory_unlock(%s)', (self.KEY,))
            except BaseException:
                # A terminated backend has already released the session lock.
                pass
            finally:
                connection.close()
