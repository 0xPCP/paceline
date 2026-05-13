"""add platform posts

Revision ID: a6d0e1f2c3b4
Revises: f3a1b2c4d5e6
Create Date: 2026-05-13
"""
from alembic import op
import sqlalchemy as sa


revision = 'a6d0e1f2c3b4'
down_revision = 'f3a1b2c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'platform_posts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('summary', sa.String(length=300), nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('is_published', sa.Boolean(), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('platform_posts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_platform_posts_published_at'), ['published_at'], unique=False)


def downgrade():
    with op.batch_alter_table('platform_posts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_platform_posts_published_at'))
    op.drop_table('platform_posts')
