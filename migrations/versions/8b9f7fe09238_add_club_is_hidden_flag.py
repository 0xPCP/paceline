"""add club is_hidden flag

Revision ID: 8b9f7fe09238
Revises: c835aa0e603f
Create Date: 2026-05-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '8b9f7fe09238'
down_revision = 'c835aa0e603f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('clubs', sa.Column('is_hidden', sa.Boolean(), nullable=False, server_default='false'))
    # Existing clubs were already public — keep them visible after migration.
    op.execute("UPDATE clubs SET is_hidden = false")
    op.alter_column('clubs', 'is_hidden', server_default=None)


def downgrade():
    op.drop_column('clubs', 'is_hidden')
