"""Add user email verification fields.

Revision ID: u8q1r0s9t8u7
Revises: t7p0q9r8s7t6
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa

revision = 'u8q1r0s9t8u7'
down_revision = 't7p0q9r8s7t6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('email_verified', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('users', sa.Column('email_verified_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('pending_email', sa.String(length=255), nullable=True))


def downgrade():
    # Intentionally no-op. The production-safe upgrade is additive only, and
    # we do not want rollback tooling to drop account email verification fields.
    pass
