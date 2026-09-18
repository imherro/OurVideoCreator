"""Immutable edit samples and retained originals, without changing old media."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision='0010_episode_samples'
down_revision='0009_episode_deliveries'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('episode_samples',
        sa.Column('id',sa.Text(),primary_key=True),
        sa.Column('project_id',sa.Text(),sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('version',sa.Integer(),nullable=False),
        sa.Column('delivery_id',sa.Text(),sa.ForeignKey('episode_deliveries.id'),nullable=False),
        sa.Column('upload_id',sa.Text(),nullable=False),
        sa.Column('original_name',sa.Text(),nullable=False),
        sa.Column('original_path',sa.Text(),nullable=False),
        sa.Column('review_path',sa.Text(),nullable=False),
        sa.Column('original_sha256',sa.Text(),nullable=False),
        sa.Column('review_sha256',sa.Text(),nullable=False),
        sa.Column('metadata',postgresql.JSONB(),nullable=False),
        sa.Column('created_by',sa.Text(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('created',sa.Double(),nullable=False),
        sa.UniqueConstraint('project_id','version'),
        sa.UniqueConstraint('project_id','upload_id'))


def downgrade():
    raise RuntimeError('Retain sample originals and version history; explicit recovery required')
