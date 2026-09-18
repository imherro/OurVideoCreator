"""Opt-in business roles and default work ownership; no historical reassignment."""
from alembic import op
import sqlalchemy as sa

revision = '0008_production_workflow'
down_revision = '0007_job_attempts'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('production_workflows',
        sa.Column('production_id', sa.Text(), sa.ForeignKey('productions.id'), primary_key=True),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('writer_id', sa.Text(), sa.ForeignKey('users.id')),
        sa.Column('artist_id', sa.Text(), sa.ForeignKey('users.id')),
        sa.Column('editor_id', sa.Text(), sa.ForeignKey('users.id')),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('updated', sa.Double(), nullable=False))
    op.create_table('production_business_roles',
        sa.Column('production_id', sa.Text(), sa.ForeignKey('production_workflows.production_id'), primary_key=True),
        sa.Column('user_id', sa.Text(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('role', sa.Text(), primary_key=True),
        sa.CheckConstraint("role IN ('producer','writer','artist','generator','editor')", name='business_role_kind'))
    op.create_table('episode_staff',
        sa.Column('project_id', sa.Text(), sa.ForeignKey('projects.id'), primary_key=True),
        sa.Column('writer_id', sa.Text(), sa.ForeignKey('users.id')),
        sa.Column('generator_id', sa.Text(), sa.ForeignKey('users.id')),
        sa.Column('editor_id', sa.Text(), sa.ForeignKey('users.id')))


def downgrade():
    # A rollback must not silently discard newly configured business ownership.
    raise RuntimeError('Workflow downgrade requires an explicit data-preserving recovery plan')
