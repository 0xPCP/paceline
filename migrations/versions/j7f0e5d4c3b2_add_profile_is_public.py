"""Add profile_is_public flag to users table.

Revision ID: j7f0e5d4c3b2
Revises: i6e9f4d3c2b1
Create Date: 2026-05-17
"""
from alembic import op
import sqlalchemy as sa

revision = 'j7f0e5d4c3b2'
down_revision = 'i6e9f4d3c2b1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('profile_is_public', sa.Boolean(),
                                      nullable=False, server_default='false'))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('profile_is_public')
