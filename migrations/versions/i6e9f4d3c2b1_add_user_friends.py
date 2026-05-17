"""Add user_friends table for bidirectional friendship with accept/decline.

Revision ID: i6e9f4d3c2b1
Revises: h5d8f3c2e1a9
Create Date: 2026-05-17
"""
from alembic import op
import sqlalchemy as sa

revision = 'i6e9f4d3c2b1'
down_revision = 'h5d8f3c2e1a9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_friends',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('requester_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('addressee_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('requester_id', 'addressee_id', name='uq_friend_request'),
    )
    op.create_index('ix_user_friends_requester', 'user_friends', ['requester_id'])
    op.create_index('ix_user_friends_addressee', 'user_friends', ['addressee_id'])


def downgrade():
    op.drop_index('ix_user_friends_addressee', table_name='user_friends')
    op.drop_index('ix_user_friends_requester', table_name='user_friends')
    op.drop_table('user_friends')
