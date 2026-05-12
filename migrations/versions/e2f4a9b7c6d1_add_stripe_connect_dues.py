"""add Stripe Connect club dues support

Revision ID: e2f4a9b7c6d1
Revises: d6a2e4f1b9c3
Create Date: 2026-05-12
"""
from alembic import op
import sqlalchemy as sa


revision = 'e2f4a9b7c6d1'
down_revision = 'd6a2e4f1b9c3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('clubs', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'membership_dues_mode',
            sa.String(length=20),
            nullable=False,
            server_default='manual',
        ))
        batch_op.add_column(sa.Column('membership_dues_amount_cents', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column(
            'membership_dues_currency',
            sa.String(length=3),
            nullable=False,
            server_default='usd',
        ))
        batch_op.add_column(sa.Column('stripe_account_id', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('stripe_account_connected_at', sa.DateTime(), nullable=True))

    op.create_table(
        'club_membership_payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('club_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('membership_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False, server_default='stripe'),
        sa.Column('provider_session_id', sa.String(length=255), nullable=True),
        sa.Column('provider_payment_intent_id', sa.String(length=255), nullable=True),
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='usd'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['club_id'], ['clubs.id']),
        sa.ForeignKeyConstraint(['membership_id'], ['club_memberships.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('club_membership_payments', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_club_membership_payments_provider_session_id'),
            ['provider_session_id'],
            unique=True,
        )


def downgrade():
    with op.batch_alter_table('club_membership_payments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_club_membership_payments_provider_session_id'))
    op.drop_table('club_membership_payments')

    with op.batch_alter_table('clubs', schema=None) as batch_op:
        batch_op.drop_column('stripe_account_connected_at')
        batch_op.drop_column('stripe_account_id')
        batch_op.drop_column('membership_dues_currency')
        batch_op.drop_column('membership_dues_amount_cents')
        batch_op.drop_column('membership_dues_mode')
