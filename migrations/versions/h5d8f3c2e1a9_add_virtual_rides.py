"""Add virtual ride fields to rides table.

Revision ID: h5d8f3c2e1a9
Revises: g4c9e2a1b7d8
Create Date: 2026-05-17
"""
from alembic import op
import sqlalchemy as sa

revision = 'h5d8f3c2e1a9'
down_revision = 'g4c9e2a1b7d8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('rides', schema=None) as batch_op:
        batch_op.alter_column('meeting_location',
                              existing_type=sa.String(length=500),
                              nullable=True)
        batch_op.add_column(sa.Column('is_virtual', sa.Boolean(),
                                      nullable=False, server_default='false'))
        batch_op.add_column(sa.Column('virtual_platform', sa.String(length=64),
                                      nullable=True))
        batch_op.add_column(sa.Column('virtual_platform_url', sa.String(length=512),
                                      nullable=True))


def downgrade():
    with op.batch_alter_table('rides', schema=None) as batch_op:
        batch_op.drop_column('virtual_platform_url')
        batch_op.drop_column('virtual_platform')
        batch_op.drop_column('is_virtual')
        batch_op.alter_column('meeting_location',
                              existing_type=sa.String(length=500),
                              nullable=False)
