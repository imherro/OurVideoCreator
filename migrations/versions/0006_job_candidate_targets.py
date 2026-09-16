"""Frozen collaboration target and explicit adoption on the existing job.

Revision ID: 0006_job_candidate_targets
Revises: 0005_owned_source_scripts
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision='0006_job_candidate_targets'
down_revision='0005_owned_source_scripts'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('jobs',sa.Column('collaboration',JSONB(),nullable=False,server_default=sa.text("'{}'::jsonb")))


def downgrade():
    op.drop_column('jobs','collaboration')
