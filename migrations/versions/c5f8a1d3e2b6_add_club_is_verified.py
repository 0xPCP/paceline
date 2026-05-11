"""add club is_verified

Revision ID: c5f8a1d3e2b6
Revises: b4e1f3a2c9d0
Create Date: 2026-05-10

"""
from alembic import op
import sqlalchemy as sa

revision = 'c5f8a1d3e2b6'
down_revision = 'b4e1f3a2c9d0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('clubs') as batch_op:
        batch_op.add_column(sa.Column('is_verified', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('clubs') as batch_op:
        batch_op.drop_column('is_verified')
