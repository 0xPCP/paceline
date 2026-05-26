"""Add new rider friendly flag to rides.

Revision ID: t7p0q9r8s7t6
Revises: s6o9p4q3r2s1
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa

revision = 't7p0q9r8s7t6'
down_revision = 's6o9p4q3r2s1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'rides',
        sa.Column(
            'is_newbie_friendly',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade():
    op.drop_column('rides', 'is_newbie_friendly')
