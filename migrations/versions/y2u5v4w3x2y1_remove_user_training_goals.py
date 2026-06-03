"""Remove accidental user training goal settings.

Revision ID: y2u5v4w3x2y1
Revises: x1t4u3v2w1x0
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = 'y2u5v4w3x2y1'
down_revision = 'x1t4u3v2w1x0'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column['name'] for column in inspector.get_columns('users')}
    if 'training_goal_value' in columns:
        op.drop_column('users', 'training_goal_value')
    if 'training_goal_mode' in columns:
        op.drop_column('users', 'training_goal_mode')


def downgrade():
    op.add_column('users', sa.Column('training_goal_mode', sa.String(length=20), nullable=True))
    op.add_column('users', sa.Column('training_goal_value', sa.Integer(), nullable=True))
