"""Add admin_messages table for superadmin ↔ club admin messaging.

Revision ID: s6o9p4q3r2s1
Revises: r5n8o3p2q1r0
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa

revision = 's6o9p4q3r2s1'
down_revision = 'r5n8o3p2q1r0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'admin_messages',
        sa.Column('id',                 sa.Integer,     primary_key=True),
        sa.Column('club_id',            sa.Integer,     sa.ForeignKey('clubs.id'),          nullable=True),
        sa.Column('sender_id',          sa.Integer,     sa.ForeignKey('users.id'),          nullable=False),
        sa.Column('is_from_superadmin', sa.Boolean,     nullable=False, server_default='1'),
        sa.Column('subject',            sa.String(300), nullable=True),
        sa.Column('body',               sa.Text,        nullable=False),
        sa.Column('created_at',         sa.DateTime,    nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('parent_id',          sa.Integer,     sa.ForeignKey('admin_messages.id'), nullable=True),
        sa.Column('is_read',            sa.Boolean,     nullable=False, server_default='0'),
    )
    op.create_index('ix_admin_messages_club_id',    'admin_messages', ['club_id'])
    op.create_index('ix_admin_messages_created_at', 'admin_messages', ['created_at'])


def downgrade():
    op.drop_index('ix_admin_messages_created_at', 'admin_messages')
    op.drop_index('ix_admin_messages_club_id',    'admin_messages')
    op.drop_table('admin_messages')
