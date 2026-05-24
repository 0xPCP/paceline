"""Add user distance_unit preference.

Revision ID: p3l6m1n0o9p8
Revises: o2k5l0m9n8o7
Create Date: 2026-05-23
"""
from alembic import op
import sqlalchemy as sa


revision = 'p3l6m1n0o9p8'
down_revision = 'o2k5l0m9n8o7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('distance_unit', sa.String(length=2), nullable=True))


def downgrade():
    op.drop_column('users', 'distance_unit')
