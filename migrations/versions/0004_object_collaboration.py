"""Independent collaboration objects; no legacy business-data import.

Revision ID: 0004_object_collaboration
Revises: 0003_platform_models
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0004_object_collaboration'
down_revision = '0003_platform_models'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'collaboration_objects',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('production_id', sa.Text(), sa.ForeignKey('productions.id'), nullable=False),
        sa.Column('project_id', sa.Text(), sa.ForeignKey('projects.id')),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('object_key', sa.Text(), nullable=False),
        sa.Column('content', JSONB(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('assignment_epoch', sa.BigInteger(), nullable=False, server_default='1'),
        sa.Column('assignee_id', sa.Text(), sa.ForeignKey('users.id')),
        sa.Column('status', sa.Text(), nullable=False, server_default='in_progress'),
        sa.Column('created_by', sa.Text(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('updated_by', sa.Text(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('updated', sa.Double(), nullable=False),
        sa.Column('deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('lease_hash', sa.Text()),
        sa.Column('lease_user_id', sa.Text(), sa.ForeignKey('users.id')),
        sa.Column('lease_epoch', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('lease_expires', sa.Double()),
        sa.CheckConstraint("kind IN ('shot','node','visual_card','graph','timeline','director')", name='collab_kind'),
        sa.CheckConstraint("status IN ('in_progress','pending_review','completed','returned')", name='collab_status'),
        sa.CheckConstraint('revision > 0 AND assignment_epoch > 0 AND lease_epoch >= 0', name='collab_counters'),
        sa.CheckConstraint("(kind='visual_card' AND project_id IS NULL) OR (kind<>'visual_card' AND project_id IS NOT NULL)", name='collab_scope'),
    )
    op.create_index('collab_production', 'collaboration_objects', ['production_id', 'kind'])
    op.create_index('collab_project', 'collaboration_objects', ['project_id', 'kind'])
    op.execute("CREATE UNIQUE INDEX collab_semantic_key ON collaboration_objects "
               "(production_id,COALESCE(project_id,''),kind,object_key)")
    op.create_index('collab_singletons', 'collaboration_objects', ['project_id', 'kind'], unique=True,
                    postgresql_where=sa.text("kind IN ('graph','timeline','director') AND NOT deleted"))
    # Composite parent FK prevents a forged Episode / Production combination.
    op.create_unique_constraint('projects_id_production', 'projects', ['id', 'production_id'])
    op.create_foreign_key('collab_episode_scope', 'collaboration_objects', 'projects',
                          ['project_id', 'production_id'], ['id', 'production_id'])
    op.create_table(
        'collaboration_history',
        sa.Column('object_id', sa.Text(), sa.ForeignKey('collaboration_objects.id'), primary_key=True),
        sa.Column('revision', sa.Integer(), primary_key=True),
        sa.Column('snapshot', JSONB(), nullable=False),
        sa.Column('actor_user_id', sa.Text(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('action', sa.Text(), nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
    )
    op.create_table(
        'collaboration_comments',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('object_id', sa.Text(), sa.ForeignKey('collaboration_objects.id'), nullable=False),
        sa.Column('actor_user_id', sa.Text(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
    )
    op.create_index('collab_comments_object', 'collaboration_comments', ['object_id', 'created'])
    op.add_column('projects', sa.Column('object_collaboration', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('projects', 'object_collaboration')
    op.drop_table('collaboration_comments')
    op.drop_table('collaboration_history')
    op.drop_table('collaboration_objects')
    op.drop_constraint('projects_id_production', 'projects', type_='unique')
