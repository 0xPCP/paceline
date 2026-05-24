"""Add full ride fields to ride_polls table

Revision ID: r5n8o3p2q1r0
Revises: q4m7n2o1p0q9
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa

revision = 'r5n8o3p2q1r0'
down_revision = 'q4m7n2o1p0q9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ride_polls', sa.Column('distance_miles', sa.Float(), nullable=True))
    op.add_column('ride_polls', sa.Column('elevation_feet', sa.Integer(), nullable=True))
    op.add_column('ride_polls', sa.Column('ride_type', sa.String(20), nullable=True))
    op.add_column('ride_polls', sa.Column('leader_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True))
    op.add_column('ride_polls', sa.Column('ride_leader', sa.String(100), nullable=True))
    op.add_column('ride_polls', sa.Column('max_riders', sa.Integer(), nullable=True))
    op.add_column('ride_polls', sa.Column('video_url', sa.String(500), nullable=True))
    op.add_column('ride_polls', sa.Column('garmin_groupride_code', sa.String(6), nullable=True))
    op.add_column('ride_polls', sa.Column('route_url', sa.String(500), nullable=True))


def downgrade():
    op.drop_column('ride_polls', 'distance_miles')
    op.drop_column('ride_polls', 'route_url')
    op.drop_column('ride_polls', 'garmin_groupride_code')
    op.drop_column('ride_polls', 'video_url')
    op.drop_column('ride_polls', 'max_riders')
    op.drop_column('ride_polls', 'ride_leader')
    op.drop_column('ride_polls', 'leader_id')
    op.drop_column('ride_polls', 'ride_type')
    op.drop_column('ride_polls', 'elevation_feet')
