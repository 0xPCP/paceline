"""add notification preferences and digest queues

Revision ID: f3a1b2c4d5e6
Revises: e2f4a9b7c6d1
Create Date: 2026-05-12
"""
from alembic import op
import sqlalchemy as sa


revision = 'f3a1b2c4d5e6'
down_revision = 'e2f4a9b7c6d1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email_preferences', sa.JSON(), nullable=True))

    op.create_table(
        'site_settings',
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', sa.String(length=500), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )
    op.execute(
        "INSERT INTO site_settings (key, value, updated_at) "
        "VALUES ('email_daily_cap', '15', CURRENT_TIMESTAMP)"
    )

    op.create_table(
        'user_email_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('notification_key', sa.String(length=80), nullable=False),
        sa.Column('subject', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('user_email_logs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_email_logs_user_created'), ['user_id', 'created_at'])

    op.create_table(
        'board_digest_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('club_id', sa.Integer(), nullable=False),
        sa.Column('post_id', sa.Integer(), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('event_type', sa.String(length=30), nullable=False),
        sa.Column('body_preview', sa.String(length=300), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id']),
        sa.ForeignKeyConstraint(['club_id'], ['clubs.id']),
        sa.ForeignKeyConstraint(['post_id'], ['club_board_posts.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('board_digest_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_board_digest_items_user_sent'), ['user_id', 'sent_at'])


def downgrade():
    with op.batch_alter_table('board_digest_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_board_digest_items_user_sent'))
    op.drop_table('board_digest_items')

    with op.batch_alter_table('user_email_logs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_email_logs_user_created'))
    op.drop_table('user_email_logs')
    op.drop_table('site_settings')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('email_preferences')
