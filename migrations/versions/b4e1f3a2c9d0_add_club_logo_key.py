"""add club logo_key

Revision ID: b4e1f3a2c9d0
Revises: a3f9d2c1b8e7
Create Date: 2026-05-10

"""
from alembic import op
import sqlalchemy as sa

revision = 'b4e1f3a2c9d0'
down_revision = 'a3f9d2c1b8e7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('clubs') as batch_op:
        batch_op.add_column(sa.Column('logo_key', sa.String(500), nullable=True))


def downgrade():
    with op.batch_alter_table('clubs') as batch_op:
        batch_op.drop_column('logo_key')
