"""Task-scoped execution leases; no automatic replay of old running work."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0007_job_attempts'
down_revision = '0006_job_candidate_targets'
branch_labels = None
depends_on = None


def upgrade():
    # Active SINGLE-01 receipt. Execution/quota tables below are retained but
    # inactive; they do not gate single-Worker submission or completion.
    op.create_table('job_submission_batches',
        sa.Column('workspace_id',sa.Text(),sa.ForeignKey('workspaces.id'),primary_key=True),
        sa.Column('actor_user_id',sa.Text(),sa.ForeignKey('users.id'),primary_key=True),
        sa.Column('namespace',sa.Text(),primary_key=True),
        sa.Column('submission_id',sa.Text(),primary_key=True),
        sa.Column('project_id',sa.Text(),sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('members',JSONB(),nullable=False),
    )
    op.add_column('jobs',sa.Column('submission_namespace',sa.Text(),nullable=False,server_default='legacy'))
    op.add_column('jobs',sa.Column('input_hash',sa.Text()))
    op.drop_constraint('jobs_submission_id_key','jobs',type_='unique')
    op.create_index('jobs_scoped_submission','jobs',
                    ['workspace_id','actor_user_id','submission_namespace','submission_id'],unique=True)
    op.create_index('jobs_legacy_submission','jobs',['submission_id'],unique=True,
                    postgresql_where=sa.text("submission_namespace='legacy'"))
    op.create_check_constraint('jobs_admission_scope','jobs',
        "submission_namespace='legacy' OR (workspace_id IS NOT NULL AND actor_user_id IS NOT NULL AND input_hash IS NOT NULL)")
    for column in (
        sa.Column('worker_id', sa.Text()),
        sa.Column('attempt_token', sa.Text()),
        sa.Column('attempt_number', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('lease_expires_at', sa.Double()),
        sa.Column('heartbeat_at', sa.Double()),
        # A legacy running task has no proof it was unsent. The claimant must
        # not infer safe replay from the absence of a provider handle.
        sa.Column('execution_phase', sa.Text(), nullable=False, server_default='legacy'),
    ):
        op.add_column('jobs', column)
    op.create_table('job_attempts',
        sa.Column('job_id', sa.Text(), sa.ForeignKey('jobs.id'), primary_key=True),
        sa.Column('number', sa.Integer(), primary_key=True),
        sa.Column('token', sa.Text(), nullable=False, unique=True),
        sa.Column('worker_id', sa.Text(), nullable=False),
        sa.Column('claimed_at', sa.Double(), nullable=False),
        sa.Column('heartbeat_at', sa.Double(), nullable=False),
        sa.Column('lease_expires_at', sa.Double(), nullable=False),
        sa.Column('ended_at', sa.Double()),
        sa.Column('outcome', sa.Text()),
    )
    op.create_index('jobs_execution_lease', 'jobs', ['status', 'lease_expires_at'])
    op.create_table('job_steps',
        sa.Column('job_id', sa.Text(), sa.ForeignKey('jobs.id'), primary_key=True),
        sa.Column('name', sa.Text(), primary_key=True),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('units', sa.Integer(), nullable=False),
        sa.Column('state', sa.Text(), nullable=False, server_default='planned'),
        sa.Column('request_hash', sa.Text()),
        sa.Column('provider_job_id', sa.Text()),
        sa.Column('response', JSONB()),
        sa.Column('submitted_at', sa.Double()),
        sa.Column('completed_at', sa.Double()),
        sa.CheckConstraint('units > 0', name='job_steps_positive_units'),
        sa.CheckConstraint("state IN ('planned','submitting','unknown','accepted','completed')", name='job_steps_state'),
    )
    op.create_table('job_outputs',
        sa.Column('job_id', sa.Text(), sa.ForeignKey('jobs.id'), primary_key=True),
        sa.Column('output_key', sa.Text(), primary_key=True),
        sa.Column('asset_id', sa.Text(), sa.ForeignKey('assets.id'), nullable=False, unique=True),
        sa.Column('content_hash', sa.Text(), nullable=False),
        sa.Column('result', JSONB(), nullable=False),
    )
    op.create_table('job_limit_settings',
        sa.Column('singleton',sa.Integer(),primary_key=True),
        sa.Column('revision',sa.Integer(),nullable=False,server_default='1'),
        sa.Column('settings',JSONB(),nullable=False,server_default=sa.text("'{}'::jsonb")),
        sa.CheckConstraint('singleton=1',name='job_limit_singleton'),
    )
    op.execute('INSERT INTO job_limit_settings(singleton) VALUES(1)')
    op.create_table('job_reservations',
        sa.Column('job_id',sa.Text(),sa.ForeignKey('jobs.id'),primary_key=True),
        sa.Column('workspace_id',sa.Text(),sa.ForeignKey('workspaces.id'),nullable=False),
        sa.Column('actor_user_id',sa.Text(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('provider_id',sa.Text(),sa.ForeignKey('model_providers.id')),
        sa.Column('quota_day',sa.Date(),nullable=False),
        sa.Column('quota_timezone',sa.Text(),nullable=False),
        sa.Column('admitted_at',sa.Double(),nullable=False),
        sa.Column('queue_expires_at',sa.Double(),nullable=False),
    )
    op.create_index('job_reservations_team_day','job_reservations',['workspace_id','quota_day'])
    op.create_index('job_reservations_user_day','job_reservations',['actor_user_id','quota_day'])
    op.create_table('job_step_usage',
        sa.Column('job_id',sa.Text(),primary_key=True),
        sa.Column('name',sa.Text(),primary_key=True),
        sa.Column('kind',sa.Text(),nullable=False),
        sa.Column('units',sa.Integer(),nullable=False),
        sa.Column('state',sa.Text(),nullable=False,server_default='reserved'),
        sa.Column('remote_open',sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.ForeignKeyConstraint(['job_id','name'],['job_steps.job_id','job_steps.name']),
        sa.CheckConstraint('units>0',name='job_usage_positive_units'),
        sa.CheckConstraint("state IN ('reserved','submitted','released')",name='job_usage_state'),
        sa.CheckConstraint("NOT remote_open OR state='submitted'",name='job_usage_remote_state'),
    )


def downgrade():
    op.drop_table('job_submission_batches')
    op.drop_table('job_step_usage')
    op.drop_table('job_reservations')
    op.drop_table('job_limit_settings')
    # Scoped keys can legitimately repeat after P6; do not silently rewrite
    # them to make an unsafe downgrade pass. PostgreSQL rejects duplicates.
    op.drop_constraint('jobs_admission_scope','jobs',type_='check')
    op.drop_index('jobs_legacy_submission',table_name='jobs')
    op.drop_index('jobs_scoped_submission',table_name='jobs')
    op.create_unique_constraint('jobs_submission_id_key','jobs',['submission_id'])
    op.drop_column('jobs','input_hash')
    op.drop_column('jobs','submission_namespace')
    op.drop_table('job_outputs')
    op.drop_table('job_steps')
    op.drop_index('jobs_execution_lease', table_name='jobs')
    op.drop_table('job_attempts')
    for name in ('execution_phase', 'heartbeat_at', 'lease_expires_at',
                 'attempt_number', 'attempt_token', 'worker_id'):
        op.drop_column('jobs', name)
