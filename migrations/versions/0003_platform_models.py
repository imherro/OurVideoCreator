"""Versioned platform model configuration and encrypted credentials.

No legacy settings/keys/jobs are copied, deleted, or rewritten.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0003_platform_models'
down_revision = '0002_identity_tenancy'
branch_labels = None
depends_on = None
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade():
    op.create_table(
        'provider_keyring',
        sa.Column('singleton', sa.Integer(), primary_key=True),
        sa.Column('key_id', sa.Text(), nullable=False),
        sa.Column('verification_ciphertext', sa.Text(), nullable=False),
        sa.CheckConstraint('singleton=1', name='provider_keyring_singleton'),
    )
    op.create_table(
        'model_providers',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('config_version_id', sa.Text()),
        sa.Column('credential_version_id', sa.Text()),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('updated', sa.Double(), nullable=False),
    )
    op.create_table(
        'provider_config_versions',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('provider_id', sa.Text(), sa.ForeignKey('model_providers.id'), nullable=False),
        sa.Column('config', JSONB, nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('created_by', sa.Text(), sa.ForeignKey('users.id')),
        sa.UniqueConstraint('provider_id', 'id', name='provider_config_owner'),
    )
    op.create_table(
        'provider_credential_versions',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('provider_id', sa.Text(), sa.ForeignKey('model_providers.id'), nullable=False),
        sa.Column('key_id', sa.Text(), nullable=False),
        sa.Column('ciphertext', sa.Text(), nullable=False),
        sa.Column('state', sa.Text(), nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('created_by', sa.Text(), sa.ForeignKey('users.id')),
        sa.Column('revoked_at', sa.Double()),
        sa.CheckConstraint("state IN ('current','retired','revoked')", name='provider_credential_state'),
        sa.UniqueConstraint('provider_id', 'id', name='provider_credential_owner'),
    )
    op.create_index('provider_one_current_key', 'provider_credential_versions', ['provider_id'],
                    unique=True, postgresql_where=sa.text("state='current'"))
    for field, target in (('config', 'provider_config_versions'), ('credential', 'provider_credential_versions')):
        op.create_foreign_key('provider_current_' + field, 'model_providers', target,
                              ['id', field + '_version_id'], ['provider_id', 'id'])
    op.create_table(
        'model_catalog',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('published', sa.Boolean(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('version_id', sa.Text()),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('updated', sa.Double(), nullable=False),
        sa.CheckConstraint("kind IN ('text','image','video','audio')", name='model_catalog_kind'),
        sa.UniqueConstraint('id', 'kind', name='model_catalog_id_kind'),
    )
    op.create_table(
        'model_versions',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('model_id', sa.Text(), sa.ForeignKey('model_catalog.id'), nullable=False),
        sa.Column('provider_id', sa.Text(), sa.ForeignKey('model_providers.id'), nullable=False),
        sa.Column('definition', JSONB, nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('created_by', sa.Text(), sa.ForeignKey('users.id')),
        sa.UniqueConstraint('model_id', 'id', name='model_version_owner'),
    )
    op.create_foreign_key('model_current_version', 'model_catalog', 'model_versions',
                          ['id', 'version_id'], ['model_id', 'id'])
    op.create_table(
        'model_defaults',
        sa.Column('kind', sa.Text(), primary_key=True),
        sa.Column('model_id', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['model_id', 'kind'], ['model_catalog.id', 'model_catalog.kind']),
    )
    # The old provider JSON column is retained solely so migration is additive.
    # New runtime bindings must never populate/read it as a credential source.
    for field, target in (('model', 'model_versions'), ('config', 'provider_config_versions'),
                          ('credential', 'provider_credential_versions')):
        op.add_column('job_private', sa.Column(field + '_version_id', sa.Text(), sa.ForeignKey(target + '.id')))
    op.add_column('job_private', sa.Column('parameters', JSONB))
    op.create_table(
        'prompt_library_state',
        sa.Column('singleton', sa.Integer(), primary_key=True),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.CheckConstraint('singleton=1', name='prompt_library_singleton'),
    )
    op.create_table(
        'prompt_templates',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('version', sa.Integer(), nullable=False),
    )
    op.create_table(
        'prompt_template_revisions',
        sa.Column('template_id', sa.Text(), sa.ForeignKey('prompt_templates.id'), primary_key=True),
        sa.Column('version', sa.Integer(), primary_key=True),
        sa.Column('snapshot', JSONB, nullable=False),
        sa.Column('created', sa.Double(), nullable=False),
        sa.Column('created_by', sa.Text(), sa.ForeignKey('users.id')),
    )


def downgrade():
    for table in ('prompt_template_revisions', 'prompt_templates', 'prompt_library_state'):
        op.drop_table(table)
    for column in ('parameters', 'credential_version_id', 'config_version_id', 'model_version_id'):
        op.drop_column('job_private', column)
    op.drop_table('model_defaults')
    op.drop_constraint('model_current_version', 'model_catalog', type_='foreignkey')
    op.drop_table('model_versions')
    op.drop_table('model_catalog')
    for field in ('config', 'credential'):
        op.drop_constraint('provider_current_' + field, 'model_providers', type_='foreignkey')
    op.drop_table('provider_credential_versions')
    op.drop_table('provider_config_versions')
    op.drop_table('model_providers')
    op.drop_table('provider_keyring')
