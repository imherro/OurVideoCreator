from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from backend.database import SCHEMA_REVISION, engine


EXPECTED_TABLES = {
    'settings', 'sessions', 'productions', 'projects', 'production_revisions',
    'source_documents', 'source_chapters', 'revisions', 'assets', 'jobs',
    'episode_scripts', 'episode_script_revisions', 'source_events', 'job_private',
    'events', 'deleted_items', 'provider_asset_groups', 'provider_asset_mappings',
    'alembic_version',
}


def test_postgresql_baseline_covers_every_retained_business_table():
    assert EXPECTED_TABLES <= set(inspect(engine()).get_table_names())
    with engine().connect() as connection:
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == SCHEMA_REVISION


def test_upgrade_head_is_repeatable_and_does_not_mutate_business_rows():
    with engine().begin() as connection:
        connection.execute(
            text("INSERT INTO settings(key,value) VALUES(:key,CAST(:value AS jsonb)) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value"),
            {'key': 'migration-repeat-probe', 'value': '{"kept": true}'},
        )
    config = Config('alembic.ini')
    command.upgrade(config, 'head')
    command.upgrade(config, 'head')
    with engine().connect() as connection:
        assert connection.execute(
            text("SELECT value->>'kept' FROM settings WHERE key='migration-repeat-probe'")
        ).scalar_one() == 'true'
