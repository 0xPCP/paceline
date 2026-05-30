"""Add club homepage layout setting.

Revision ID: v9r2s1t0u9v8
Revises: u8q1r0s9t8u7
Create Date: 2026-05-30
"""
from alembic import op
import sqlalchemy as sa

revision = 'v9r2s1t0u9v8'
down_revision = 'u8q1r0s9t8u7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'clubs',
        sa.Column(
            'homepage_layout',
            sa.String(length=20),
            nullable=False,
            server_default='magazine',
        ),
    )


def downgrade():
    op.drop_column('clubs', 'homepage_layout')
