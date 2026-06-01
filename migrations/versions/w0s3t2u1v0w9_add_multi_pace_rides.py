"""Add multi-pace ride fields.

Revision ID: w0s3t2u1v0w9
Revises: v9r2s1t0u9v8
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa

revision = 'w0s3t2u1v0w9'
down_revision = 'v9r2s1t0u9v8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'rides',
        sa.Column('is_multi_pace', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.add_column('rides', sa.Column('pace_categories', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('rides', 'pace_categories')
    op.drop_column('rides', 'is_multi_pace')
