"""Invite-only identity, workspaces, production membership, and audit scope.

Revision ID: 0002_identity_tenancy
Revises: 0001_postgresql_baseline
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0002_identity_tenancy'
down_revision = '0001_postgresql_baseline'
branch_labels = None
depends_on = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    # P2 sessions represented one shared studio password. P3 intentionally
    # retires them instead of attempting to turn an anonymous session into a
    # personal account.
    op.drop_table('sessions')
    op.create_table(
        'users',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('phone', sa.Text(), nullable=False, unique=True),
        sa.Column('nickname', sa.Text(), nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('platform_role', sa.Text(), nullable=False, server_default='user'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('phone_verified_at', sa.Double()),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('updated', sa.Double(), nullable=False),
        sa.CheckConstraint("platform_role IN ('platform_admin','user')", name='users_platform_role'),
    )
    op.create_table(
        'sessions',
        sa.Column('token_hash', sa.Text(), primary_key=True),
        sa.Column('user_id', sa.Text(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('csrf_hash', sa.Text(), nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('expires', sa.Double(), nullable=False),
        sa.Column('last_seen', sa.Double(), nullable=False),
        sa.Column('revoked_at', sa.Double()),
    )
    op.create_table(
        'invitations',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('token_hash', sa.Text(), nullable=False, unique=True),
        sa.Column('created_by', sa.Text(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('expires', sa.Double(), nullable=False),
        sa.Column('revoked_at', sa.Double()),
        sa.Column('consumed_at', sa.Double()),
        sa.Column('consumed_by', sa.Text(), sa.ForeignKey('users.id')),
        sa.Column('note', sa.Text(), nullable=False, server_default=''),
    )
    op.create_table(
        'password_reset_tokens',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('token_hash', sa.Text(), nullable=False, unique=True),
        sa.Column('user_id', sa.Text(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by', sa.Text(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('expires', sa.Double(), nullable=False),
        sa.Column('revoked_at', sa.Double()),
        sa.Column('consumed_at', sa.Double()),
    )
    op.create_table(
        'workspaces',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('created_by', sa.Text(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('updated', sa.Double(), nullable=False),
    )
    op.create_table(
        'workspace_members',
        sa.Column('workspace_id', sa.Text(), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('user_id', sa.Text(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('role', sa.Text(), nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
        sa.CheckConstraint("role IN ('owner','member')", name='workspace_members_role'),
    )
    op.create_table(
        'production_members',
        sa.Column('production_id', sa.Text(), sa.ForeignKey('productions.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('user_id', sa.Text(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('role', sa.Text(), nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
        sa.CheckConstraint("role IN ('manager','editor','viewer')", name='production_members_role'),
    )
    op.create_table(
        'auth_rate_limits',
        sa.Column('key', sa.Text(), primary_key=True),
        sa.Column('window_started', sa.Double(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('blocked_until', sa.Double()),
    )
    op.create_table(
        'audit_events',
        sa.Column('id', sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column('actor_user_id', sa.Text(), sa.ForeignKey('users.id')),
        sa.Column('action', sa.Text(), nullable=False),
        sa.Column('target_type', sa.Text(), nullable=False),
        sa.Column('target_id', sa.Text()),
        sa.Column('workspace_id', sa.Text(), sa.ForeignKey('workspaces.id')),
        sa.Column('production_id', sa.Text(), sa.ForeignKey('productions.id')),
        sa.Column('payload', JSONB, nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
    )

    op.add_column('productions', sa.Column('workspace_id', sa.Text()))
    op.create_foreign_key('productions_workspace_fk', 'productions', 'workspaces', ['workspace_id'], ['id'])
    op.add_column('jobs', sa.Column('workspace_id', sa.Text()))
    op.add_column('jobs', sa.Column('actor_user_id', sa.Text()))
    op.create_foreign_key('jobs_workspace_fk', 'jobs', 'workspaces', ['workspace_id'], ['id'])
    op.create_foreign_key('jobs_actor_fk', 'jobs', 'users', ['actor_user_id'], ['id'])
    op.add_column('events', sa.Column('workspace_id', sa.Text()))
    op.add_column('events', sa.Column('production_id', sa.Text()))
    op.create_foreign_key('events_workspace_fk', 'events', 'workspaces', ['workspace_id'], ['id'])
    op.create_foreign_key('events_production_fk', 'events', 'productions', ['production_id'], ['id'])

    op.create_index('sessions_user_active', 'sessions', ['user_id', 'expires'])
    op.create_index('invitations_expires', 'invitations', ['expires'])
    op.create_index('password_reset_user_expires', 'password_reset_tokens', ['user_id', 'expires'])
    op.create_index('workspace_members_user', 'workspace_members', ['user_id', 'workspace_id'])
    op.create_index('production_members_user', 'production_members', ['user_id', 'production_id'])
    op.create_index('productions_workspace_updated', 'productions', ['workspace_id', 'updated'])
    op.create_index('jobs_workspace_created', 'jobs', ['workspace_id', 'created'])
    op.create_index('events_scope_id', 'events', ['workspace_id', 'production_id', 'id'])
    op.create_index('audit_scope_created', 'audit_events', ['workspace_id', 'production_id', 'created'])


def downgrade() -> None:
    for table, columns in (
        ('events', ('production_id', 'workspace_id')),
        ('jobs', ('actor_user_id', 'workspace_id')),
        ('productions', ('workspace_id',)),
    ):
        for column in columns:
            op.drop_column(table, column)
    for table in (
        'audit_events', 'auth_rate_limits', 'production_members', 'workspace_members',
        'workspaces', 'password_reset_tokens', 'invitations', 'sessions', 'users',
    ):
        op.drop_table(table)
    op.create_table(
        'sessions',
        sa.Column('token', sa.Text(), primary_key=True),
        sa.Column('expires', sa.Double(), nullable=False),
    )
