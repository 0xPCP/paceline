"""add logo_key to club_sponsors and image_key to club_posts

Revision ID: a3f9d2c1b8e7
Revises: 7f195bdf2f2f
Create Date: 2026-05-10 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a3f9d2c1b8e7'
down_revision = '7f195bdf2f2f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('club_sponsors', schema=None) as batch_op:
        batch_op.add_column(sa.Column('logo_key', sa.String(length=500), nullable=True))

    with op.batch_alter_table('club_posts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('image_key', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('club_posts', schema=None) as batch_op:
        batch_op.drop_column('image_key')

    with op.batch_alter_table('club_sponsors', schema=None) as batch_op:
        batch_op.drop_column('logo_key')
