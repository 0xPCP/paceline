"""Add profile_photo_key to users and user_bikes table.

Revision ID: l9h2i7j6k5l4
Revises: k8g1h6i5j4k3
Create Date: 2026-05-17
"""
from alembic import op
import sqlalchemy as sa

revision = 'l9h2i7j6k5l4'
down_revision = 'k8g1h6i5j4k3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('profile_photo_key', sa.String(200), nullable=True))

    op.create_table(
        'user_bikes',
        sa.Column('id',            sa.Integer(), nullable=False),
        sa.Column('user_id',       sa.Integer(), nullable=False),
        sa.Column('make_model',    sa.String(100), nullable=False),
        sa.Column('nickname',      sa.String(50), nullable=True),
        sa.Column('bike_type',     sa.String(20), nullable=False, server_default='road'),
        sa.Column('is_primary',    sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at',    sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_user_bikes_user_id', 'user_bikes', ['user_id'])


def downgrade():
    op.drop_index('ix_user_bikes_user_id', table_name='user_bikes')
    op.drop_table('user_bikes')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('profile_photo_key')
