"""Add dues_edit_logs table.

Revision ID: n1j4k9l8m7n6
Revises: m0i3j8k7l6m5
Create Date: 2026-05-18
"""
from alembic import op
import sqlalchemy as sa

revision = 'n1j4k9l8m7n6'
down_revision = 'm0i3j8k7l6m5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'dues_edit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('membership_id', sa.Integer(), sa.ForeignKey('club_memberships.id'), nullable=False),
        sa.Column('edited_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('edited_at', sa.DateTime(), nullable=False),
        sa.Column('old_dues_paid_until', sa.Date(), nullable=True),
        sa.Column('new_dues_paid_until', sa.Date(), nullable=True),
        sa.Column('old_status', sa.String(20), nullable=True),
        sa.Column('new_status', sa.String(20), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('dues_edit_logs')
