"""Add ride poll tables

Revision ID: q4m7n2o1p0q9
Revises: p3l6m1n0o9p8
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa

revision = 'q4m7n2o1p0q9'
down_revision = 'p3l6m1n0o9p8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ride_polls',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('club_id', sa.Integer(), sa.ForeignKey('clubs.id'), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('ride_date', sa.Date(), nullable=False),
        sa.Column('default_start_time', sa.Time(), nullable=True),
        sa.Column('pace_category', sa.String(2), nullable=True),
        sa.Column('meeting_location', sa.String(500), nullable=True),
        sa.Column('closes_at', sa.DateTime(), nullable=False),
        sa.Column('finalize_mode', sa.String(10), nullable=False, server_default='manual'),
        sa.Column('status', sa.String(12), nullable=False, server_default='open'),
        sa.Column('ride_id', sa.Integer(), sa.ForeignKey('rides.id'), nullable=True),
        sa.Column('poll_length', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('poll_course', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('poll_start_time', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ride_polls_club_id', 'ride_polls', ['club_id'])
    op.create_index('ix_ride_polls_ride_date', 'ride_polls', ['ride_date'])

    op.create_table(
        'ride_poll_options',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('poll_id', sa.Integer(), sa.ForeignKey('ride_polls.id'), nullable=False),
        sa.Column('category', sa.String(20), nullable=False),
        sa.Column('value', sa.String(200), nullable=False),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('first_voted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ride_poll_options_poll_id', 'ride_poll_options', ['poll_id'])

    op.create_table(
        'ride_poll_votes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('poll_id', sa.Integer(), sa.ForeignKey('ride_polls.id'), nullable=False),
        sa.Column('option_id', sa.Integer(), sa.ForeignKey('ride_poll_options.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('category', sa.String(20), nullable=False),
        sa.Column('voted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('poll_id', 'user_id', 'category', name='uq_poll_user_category'),
    )
    op.create_index('ix_ride_poll_votes_poll_id', 'ride_poll_votes', ['poll_id'])


def downgrade():
    op.drop_table('ride_poll_votes')
    op.drop_table('ride_poll_options')
    op.drop_table('ride_polls')
