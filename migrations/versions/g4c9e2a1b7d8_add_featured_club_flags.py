"""add featured club flags

Revision ID: g4c9e2a1b7d8
Revises: f3a1b2c4d5e6
Create Date: 2026-05-13
"""
from alembic import op
import sqlalchemy as sa


revision = 'g4c9e2a1b7d8'
down_revision = 'f3a1b2c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('clubs', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'is_featured',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ))
        batch_op.add_column(sa.Column('featured_rank', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('clubs', schema=None) as batch_op:
        batch_op.drop_column('featured_rank')
        batch_op.drop_column('is_featured')
