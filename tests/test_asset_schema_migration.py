from sqlalchemy import inspect

from backend.database import engine


def test_postgresql_baseline_has_asset_ownership_and_lookup_indexes():
    inspector = inspect(engine())
    columns = {item['name']: item for item in inspector.get_columns('assets')}
    indexes = {item['name']: item for item in inspector.get_indexes('assets')}
    assert {'production_id', 'project_id', 'category', 'source', 'metadata'} <= columns.keys()
    assert columns['metadata']['type'].__class__.__name__ == 'JSONB'
    assert {
        'assets_project_created',
        'assets_project_category_created',
        'assets_production_created',
        'assets_production_category_created',
    } <= indexes.keys()
