"""PostgreSQL baseline for every retained business table.

Revision ID: 0001_postgresql_baseline
Revises: None
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0001_postgresql_baseline'
down_revision = None
branch_labels = None
depends_on = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        'settings',
        sa.Column('key', sa.Text(), primary_key=True),
        sa.Column('value', JSONB, nullable=False),
    )
    op.create_table(
        'sessions',
        sa.Column('token', sa.Text(), primary_key=True),
        sa.Column('expires', sa.Double(), nullable=False),
    )
    op.create_table(
        'productions',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('shared_context', JSONB),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('updated', sa.Double(), nullable=False),
    )
    op.create_table(
        'projects',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('document', JSONB, nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('updated', sa.Double(), nullable=False),
        sa.Column('production_id', sa.Text(), sa.ForeignKey('productions.id')),
        sa.Column('episode_no', sa.Integer()),
        sa.Column('episode_title', sa.Text()),
    )
    op.create_table(
        'production_revisions',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('production_id', sa.Text(), sa.ForeignKey('productions.id'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('shared_context', JSONB, nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
    )
    op.create_table(
        'source_documents',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('production_id', sa.Text(), sa.ForeignKey('productions.id'), nullable=False),
        sa.Column('type', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('metadata', JSONB, nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('updated', sa.Double(), nullable=False),
    )
    op.create_table(
        'source_chapters',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('source_id', sa.Text(), sa.ForeignKey('source_documents.id'), nullable=False),
        sa.Column('chapter_no', sa.Integer(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('updated', sa.Double(), nullable=False),
        sa.UniqueConstraint('source_id', 'chapter_no', name='source_chapters_number'),
    )
    op.create_table(
        'revisions',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('project_id', sa.Text(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('document', JSONB, nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
    )
    op.create_table(
        'assets',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('project_id', sa.Text(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('path', sa.Text(), nullable=False),
        sa.Column('mime', sa.Text(), nullable=False),
        sa.Column('metadata', JSONB, nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('category', sa.Text(), nullable=False, server_default='other'),
        sa.Column('source', sa.Text(), nullable=False, server_default='uploaded'),
        sa.Column('production_id', sa.Text(), sa.ForeignKey('productions.id')),
    )
    op.create_table(
        'jobs',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('submission_id', sa.Text(), nullable=False, unique=True),
        sa.Column('project_id', sa.Text(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('node_id', sa.Text(), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('input', JSONB, nullable=False),
        sa.Column('result', JSONB),
        sa.Column('provider_job_id', sa.Text()),
        sa.Column('error', sa.Text()),
        sa.Column('phase', sa.Text(), nullable=False, server_default=''),
        sa.Column('progress', sa.Double()),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('updated', sa.Double(), nullable=False),
        sa.Column('started', sa.Double()),
        sa.Column('finished', sa.Double()),
        sa.Column('telemetry', JSONB),
        sa.Column('scope', sa.Text(), nullable=False, server_default='episode'),
        sa.Column('production_id', sa.Text(), sa.ForeignKey('productions.id')),
    )
    op.create_table(
        'episode_scripts',
        sa.Column('project_id', sa.Text(), sa.ForeignKey('projects.id'), primary_key=True),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('synopsis', sa.Text(), nullable=False),
        sa.Column('source_chapter_refs', JSONB, nullable=False),
        sa.Column('story_goal', sa.Text(), nullable=False),
        sa.Column('paywall_beat', JSONB, nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('estimated_duration', sa.Double(), nullable=False),
        sa.Column('characters', JSONB, nullable=False),
        sa.Column('scenes', JSONB, nullable=False),
        sa.Column('props', JSONB, nullable=False),
        sa.Column('generation_job_id', sa.Text(), sa.ForeignKey('jobs.id')),
        sa.Column('metadata', JSONB, nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('updated', sa.Double(), nullable=False),
    )
    op.create_table(
        'episode_script_revisions',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('project_id', sa.Text(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('snapshot', JSONB, nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
    )
    op.create_table(
        'source_events',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('production_id', sa.Text(), sa.ForeignKey('productions.id'), nullable=False),
        sa.Column('chapter_id', sa.Text(), sa.ForeignKey('source_chapters.id'), nullable=False),
        sa.Column('event_order', sa.Integer(), nullable=False),
        sa.Column('characters', JSONB, nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('importance', sa.Text(), nullable=False),
        sa.Column('emotion', sa.Text(), nullable=False),
        sa.Column('continuity', JSONB, nullable=False),
        sa.Column('extraction_job_id', sa.Text(), sa.ForeignKey('jobs.id')),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('updated', sa.Double(), nullable=False),
    )
    op.create_table(
        'job_private',
        sa.Column('job_id', sa.Text(), sa.ForeignKey('jobs.id'), primary_key=True),
        sa.Column('provider', JSONB, nullable=False),
    )
    op.create_table(
        'events',
        sa.Column('id', sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column('project_id', sa.Text()),
        sa.Column('payload', JSONB, nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
    )
    op.create_table(
        'deleted_items',
        sa.Column('kind', sa.Text(), primary_key=True),
        sa.Column('item_id', sa.Text(), primary_key=True),
        sa.Column('project_id', sa.Text()),
        sa.Column('deleted_at', sa.Double(), nullable=False),
    )
    op.create_table(
        'provider_asset_groups',
        sa.Column('provider_id', sa.Text(), primary_key=True),
        sa.Column('account_hash', sa.Text(), primary_key=True),
        sa.Column('remote_group_id', sa.Text(), nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('updated', sa.Double(), nullable=False),
    )
    op.create_table(
        'provider_asset_mappings',
        sa.Column('provider_id', sa.Text(), primary_key=True),
        sa.Column('account_hash', sa.Text(), primary_key=True),
        sa.Column('local_asset_id', sa.Text(), sa.ForeignKey('assets.id'), primary_key=True),
        sa.Column('remote_asset_id', sa.Text(), nullable=False),
        sa.Column('remote_group_id', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('error', sa.Text()),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('updated', sa.Double(), nullable=False),
    )

    op.create_index('projects_production_updated', 'projects', ['production_id', 'updated'])
    op.create_index(
        'projects_production_episode', 'projects', ['production_id', 'episode_no'], unique=True,
        postgresql_where=sa.text('production_id IS NOT NULL'),
    )
    op.create_index('production_revisions_parent_revision', 'production_revisions', ['production_id', 'revision'], unique=True)
    op.create_index('source_documents_production', 'source_documents', ['production_id', 'updated'])
    op.create_index('source_chapters_source_order', 'source_chapters', ['source_id', 'sort_order'])
    op.create_index('revisions_project_revision', 'revisions', ['project_id', 'revision'], unique=True)
    op.create_index('assets_project_created', 'assets', ['project_id', 'created'])
    op.create_index('assets_project_category_created', 'assets', ['project_id', 'category', 'created'])
    op.create_index('assets_production_created', 'assets', ['production_id', 'created'])
    op.create_index('assets_production_category_created', 'assets', ['production_id', 'category', 'created'])
    op.create_index('jobs_project_created', 'jobs', ['project_id', 'created'])
    op.create_index('jobs_status_created', 'jobs', ['status', 'created'])
    op.create_index('jobs_production_created', 'jobs', ['production_id', 'created'])
    op.create_index('episode_scripts_status', 'episode_scripts', ['status', 'updated'])
    op.create_index('episode_script_revisions_parent', 'episode_script_revisions', ['project_id', 'revision'], unique=True)
    op.create_index('source_events_production_chapter', 'source_events', ['production_id', 'chapter_id', 'event_order'])
    op.create_index('deleted_items_project', 'deleted_items', ['project_id', 'deleted_at'])
    op.create_index(
        'provider_asset_mappings_remote', 'provider_asset_mappings',
        ['provider_id', 'account_hash', 'remote_asset_id'], unique=True,
    )


def downgrade() -> None:
    for table in (
        'provider_asset_mappings', 'provider_asset_groups', 'deleted_items', 'events',
        'job_private', 'source_events', 'episode_script_revisions', 'episode_scripts',
        'jobs', 'assets', 'revisions', 'source_chapters', 'source_documents',
        'production_revisions', 'projects', 'productions', 'sessions', 'settings',
    ):
        op.drop_table(table)
