"""Add user training goal settings.

Revision ID: x1t4u3v2w1x0
Revises: w0s3t2u1v0w9
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = 'x1t4u3v2w1x0'
down_revision = 'w0s3t2u1v0w9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('training_goal_mode', sa.String(length=20), nullable=True))
    op.add_column('users', sa.Column('training_goal_value', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('users', 'training_goal_value')
    op.drop_column('users', 'training_goal_mode')
