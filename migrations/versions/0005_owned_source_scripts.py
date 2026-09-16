"""Ownership on existing source/script sources, without copying legacy content.

Revision ID: 0005_owned_source_scripts
Revises: 0004_object_collaboration
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision='0005_owned_source_scripts'
down_revision='0004_object_collaboration'
branch_labels=None
depends_on=None


def upgrade():
    for table in ('episode_scripts','source_chapters'):
        for name in ('assignee_id','created_by','updated_by'):
            op.add_column(table,sa.Column(name,sa.Text(),sa.ForeignKey('users.id')))
        op.add_column(table,sa.Column('assignment_epoch',sa.BigInteger(),nullable=False,server_default='1'))
        op.create_check_constraint(table+'_assignment_epoch',table,'assignment_epoch > 0')
        op.create_index(table+'_assignee',table,['assignee_id'])
    op.add_column('source_chapters',sa.Column('status',sa.Text(),nullable=False,server_default='in_progress'))
    op.create_check_constraint('chapter_review_status','source_chapters',"status IN ('in_progress','pending_review','completed','returned')")
    op.create_table('source_chapter_revisions',
        sa.Column('chapter_id',sa.Text(),sa.ForeignKey('source_chapters.id'),primary_key=True),
        sa.Column('revision',sa.Integer(),primary_key=True),
        sa.Column('snapshot',JSONB(),nullable=False),
        sa.Column('actor_user_id',sa.Text(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('action',sa.Text(),nullable=False),
        sa.Column('created',sa.Double(),nullable=False))
    op.create_table('source_script_comments',
        sa.Column('id',sa.Text(),primary_key=True),
        sa.Column('project_id',sa.Text(),sa.ForeignKey('episode_scripts.project_id')),
        sa.Column('chapter_id',sa.Text(),sa.ForeignKey('source_chapters.id')),
        sa.Column('actor_user_id',sa.Text(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('body',sa.Text(),nullable=False),
        sa.Column('created',sa.Double(),nullable=False),
        sa.CheckConstraint('(project_id IS NULL) <> (chapter_id IS NULL)',name='source_script_comment_parent'))
    op.create_index('source_script_comments_script','source_script_comments',['project_id','created'])
    op.create_index('source_script_comments_chapter','source_script_comments',['chapter_id','created'])


def downgrade():
    op.drop_table('source_script_comments')
    op.drop_table('source_chapter_revisions')
    op.drop_constraint('chapter_review_status','source_chapters',type_='check')
    op.drop_column('source_chapters','status')
    for table in ('episode_scripts','source_chapters'):
        op.drop_index(table+'_assignee',table)
        op.drop_constraint(table+'_assignment_epoch',table,type_='check')
        for name in ('assignee_id','created_by','updated_by','assignment_epoch'):
            op.drop_column(table,name)
