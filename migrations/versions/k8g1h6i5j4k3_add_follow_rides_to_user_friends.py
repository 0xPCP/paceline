"""Add follow_rides flag to user_friends.

Revision ID: k8g1h6i5j4k3
Revises: j7f0e5d4c3b2
Create Date: 2026-05-17
"""
from alembic import op
import sqlalchemy as sa

revision = 'k8g1h6i5j4k3'
down_revision = 'j7f0e5d4c3b2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_friends', schema=None) as batch_op:
        batch_op.add_column(sa.Column('follow_rides', sa.Boolean(),
                                      nullable=False, server_default='true'))


def downgrade():
    with op.batch_alter_table('user_friends', schema=None) as batch_op:
        batch_op.drop_column('follow_rides')
