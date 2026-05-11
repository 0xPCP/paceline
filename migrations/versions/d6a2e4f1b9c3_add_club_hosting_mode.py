"""add club hosting_mode column

Revision ID: d6a2e4f1b9c3
Revises: c5f8a1d3e2b6
Create Date: 2026-05-10
"""
from alembic import op
import sqlalchemy as sa

revision = 'd6a2e4f1b9c3'
down_revision = 'c5f8a1d3e2b6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('clubs', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'hosting_mode', sa.String(length=20),
            nullable=False, server_default='full',
        ))


def downgrade():
    with op.batch_alter_table('clubs', schema=None) as batch_op:
        batch_op.drop_column('hosting_mode')
