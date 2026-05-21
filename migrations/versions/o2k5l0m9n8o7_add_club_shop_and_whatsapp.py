"""Add club shop and WhatsApp link.

Revision ID: o2k5l0m9n8o7
Revises: n1j4k9l8m7n6
Create Date: 2026-05-20
"""
from alembic import op
import sqlalchemy as sa


revision = 'o2k5l0m9n8o7'
down_revision = 'n1j4k9l8m7n6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('recommendations_enabled', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('users', sa.Column('recommendation_location_enabled', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('users', sa.Column('recommendation_history_enabled', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('users', sa.Column('recommendation_friend_activity_enabled', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('users', sa.Column('dashboard_recommendations_hidden', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('users', sa.Column('recommendation_ride_types', sa.JSON(), nullable=True))

    op.add_column('clubs', sa.Column('whatsapp_url', sa.String(length=500), nullable=True))
    op.add_column('clubs', sa.Column('shop_tax_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('clubs', sa.Column('shop_shipping_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('clubs', sa.Column('shop_shipping_fee_cents', sa.Integer(), nullable=True))
    op.add_column('clubs', sa.Column('shop_shipping_countries', sa.String(length=255), nullable=False, server_default='US'))

    op.create_table(
        'club_shop_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('club_id', sa.Integer(), sa.ForeignKey('clubs.id'), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('image_url', sa.String(length=500), nullable=True),
        sa.Column('price_cents', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='usd'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('fulfillment_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'club_shop_orders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('club_id', sa.Integer(), sa.ForeignKey('clubs.id'), nullable=False),
        sa.Column('item_id', sa.Integer(), sa.ForeignKey('club_shop_items.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False, server_default='stripe'),
        sa.Column('provider_session_id', sa.String(length=255), nullable=True),
        sa.Column('provider_payment_intent_id', sa.String(length=255), nullable=True),
        sa.Column('item_amount_cents', sa.Integer(), nullable=False),
        sa.Column('platform_fee_cents', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('tax_amount_cents', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('shipping_amount_cents', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='usd'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('customer_email', sa.String(length=255), nullable=True),
        sa.Column('customer_name', sa.String(length=255), nullable=True),
        sa.Column('shipping_details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_club_shop_orders_provider_session_id', 'club_shop_orders', ['provider_session_id'], unique=True)
    op.create_table(
        'user_recommendation_hidden',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('target_type', sa.String(length=20), nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(length=40), nullable=False, server_default='hidden'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'target_type', 'target_id', name='uq_user_recommendation_hidden'),
    )


def downgrade():
    op.drop_table('user_recommendation_hidden')
    op.drop_index('ix_club_shop_orders_provider_session_id', table_name='club_shop_orders')
    op.drop_table('club_shop_orders')
    op.drop_table('club_shop_items')
    op.drop_column('clubs', 'shop_shipping_countries')
    op.drop_column('clubs', 'shop_shipping_fee_cents')
    op.drop_column('clubs', 'shop_shipping_enabled')
    op.drop_column('clubs', 'shop_tax_enabled')
    op.drop_column('clubs', 'whatsapp_url')
    op.drop_column('users', 'recommendation_ride_types')
    op.drop_column('users', 'dashboard_recommendations_hidden')
    op.drop_column('users', 'recommendation_friend_activity_enabled')
    op.drop_column('users', 'recommendation_history_enabled')
    op.drop_column('users', 'recommendation_location_enabled')
    op.drop_column('users', 'recommendations_enabled')
