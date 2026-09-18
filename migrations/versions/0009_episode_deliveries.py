"""Immutable selected-media handoffs; existing projects/content remain untouched."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0009_episode_deliveries'
down_revision = '0008_production_workflow'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('episode_deliveries',
        sa.Column('id',sa.Text(),primary_key=True),
        sa.Column('project_id',sa.Text(),sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('version',sa.Integer(),nullable=False),
        sa.Column('fingerprint',sa.Text(),nullable=False),
        sa.Column('manifest',postgresql.JSONB(),nullable=False),
        sa.Column('archive_name',sa.Text(),nullable=False),
        sa.Column('archive_sha256',sa.Text(),nullable=False),
        sa.Column('created_by',sa.Text(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('created',sa.Double(),nullable=False),
        sa.UniqueConstraint('project_id','version'),
        sa.UniqueConstraint('project_id','fingerprint'))


def downgrade():
    raise RuntimeError('Retain delivery history; use an explicit data-preserving recovery plan')
