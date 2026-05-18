"""Add dues_reminder_sent to club_memberships.

Revision ID: m0i3j8k7l6m5
Revises: l9h2i7j6k5l4
Create Date: 2026-05-18
"""
from alembic import op
import sqlalchemy as sa

revision = 'm0i3j8k7l6m5'
down_revision = 'l9h2i7j6k5l4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('club_memberships', sa.Column('dues_reminder_sent', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('club_memberships', 'dues_reminder_sent')
