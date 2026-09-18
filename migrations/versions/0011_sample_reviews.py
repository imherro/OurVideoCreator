"""Append-only frame comments, replies and exact-version decisions."""
from alembic import op
import sqlalchemy as sa

revision='0011_sample_reviews'
down_revision='0010_episode_samples'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('sample_review_events',
        sa.Column('id',sa.Text(),primary_key=True),
        sa.Column('project_id',sa.Text(),sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('sample_id',sa.Text(),sa.ForeignKey('episode_samples.id'),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('kind',sa.Text(),nullable=False),
        sa.Column('frame',sa.Integer()),
        sa.Column('parent_id',sa.Text(),sa.ForeignKey('sample_review_events.id')),
        sa.Column('related_sample_id',sa.Text(),sa.ForeignKey('episode_samples.id')),
        sa.Column('body',sa.Text(),nullable=False),
        sa.Column('created_by',sa.Text(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('created',sa.Double(),nullable=False),
        sa.UniqueConstraint('project_id','revision'),
        sa.CheckConstraint("kind IN ('comment','reply','resolve','reopen','approve','return')"))


def downgrade():
    raise RuntimeError('Retain review history; explicit recovery required')
