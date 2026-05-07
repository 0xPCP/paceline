"""Small runtime schema guards for deployments without Alembic."""
from flask import current_app
from sqlalchemy import inspect, text

from .extensions import db


def _configured_superadmin_emails():
    raw = current_app.config.get('SUPERADMIN_EMAILS', '')
    return {
        email.strip().lower()
        for email in raw.split(',')
        if email.strip()
    }


def ensure_runtime_schema():
    """Apply additive schema fixes required by current code.

    The project currently uses db.create_all() instead of Alembic migrations.
    create_all() does not add columns to existing tables, so keep this limited
    to safe additive changes needed by deployed dev databases.
    """
    inspector = inspect(db.engine)
    if 'users' not in inspector.get_table_names():
        return

    user_columns = {col['name'] for col in inspector.get_columns('users')}
    changed = False

    if 'session_token_version' not in user_columns:
        ddl = 'ALTER TABLE users ADD COLUMN session_token_version INTEGER NOT NULL DEFAULT 0'
        db.session.execute(text(ddl))
        changed = True

    if 'username_finalized' not in user_columns:
        db.session.execute(text('ALTER TABLE users ADD COLUMN username_finalized BOOLEAN NOT NULL DEFAULT TRUE'))
        changed = True

    if 'google_sub' not in user_columns:
        db.session.execute(text('ALTER TABLE users ADD COLUMN google_sub VARCHAR(255)'))
        changed = True

    if 'mfa_enabled' not in user_columns:
        db.session.execute(text('ALTER TABLE users ADD COLUMN mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE'))
        changed = True

    if 'mfa_secret' not in user_columns:
        db.session.execute(text('ALTER TABLE users ADD COLUMN mfa_secret VARCHAR(64)'))
        changed = True

    if 'mfa_backup_codes' not in user_columns:
        db.session.execute(text('ALTER TABLE users ADD COLUMN mfa_backup_codes JSON'))
        changed = True

    if 'sport_preferences' not in user_columns:
        db.session.execute(text('ALTER TABLE users ADD COLUMN sport_preferences JSON'))
        changed = True

    if 'strava_profile_url' not in user_columns:
        db.session.execute(text('ALTER TABLE users ADD COLUMN strava_profile_url VARCHAR(500)'))
        changed = True

    club_columns = {col['name'] for col in inspector.get_columns('clubs')} if 'clubs' in inspector.get_table_names() else set()
    if club_columns and 'sport_type' not in club_columns:
        db.session.execute(text("ALTER TABLE clubs ADD COLUMN sport_type VARCHAR(20) NOT NULL DEFAULT 'cycling'"))
        changed = True
    if club_columns and 'owner_id' not in club_columns:
        db.session.execute(text('ALTER TABLE clubs ADD COLUMN owner_id INTEGER'))
        changed = True
    if club_columns and 'membership_dues_required' not in club_columns:
        db.session.execute(text('ALTER TABLE clubs ADD COLUMN membership_dues_required BOOLEAN NOT NULL DEFAULT FALSE'))
        changed = True
    if club_columns and 'membership_dues_url' not in club_columns:
        db.session.execute(text('ALTER TABLE clubs ADD COLUMN membership_dues_url VARCHAR(500)'))
        changed = True
    if club_columns and 'membership_duration_months' not in club_columns:
        db.session.execute(text('ALTER TABLE clubs ADD COLUMN membership_duration_months INTEGER NOT NULL DEFAULT 12'))
        changed = True

    membership_columns = (
        {col['name'] for col in inspector.get_columns('club_memberships')}
        if 'club_memberships' in inspector.get_table_names() else set()
    )
    if membership_columns and 'dues_paid_until' not in membership_columns:
        db.session.execute(text('ALTER TABLE club_memberships ADD COLUMN dues_paid_until DATE'))
        changed = True
    if membership_columns and 'dues_confirmed_at' not in membership_columns:
        db.session.execute(text('ALTER TABLE club_memberships ADD COLUMN dues_confirmed_at TIMESTAMP'))
        changed = True
    if membership_columns and 'dues_confirmed_by_id' not in membership_columns:
        db.session.execute(text('ALTER TABLE club_memberships ADD COLUMN dues_confirmed_by_id INTEGER'))
        changed = True
    if membership_columns and db.engine.dialect.name == 'postgresql':
        status_col = next(
            (col for col in inspector.get_columns('club_memberships') if col['name'] == 'status'),
            None,
        )
        if status_col is not None and getattr(status_col['type'], 'length', None) and status_col['type'].length < 20:
            db.session.execute(text('ALTER TABLE club_memberships ALTER COLUMN status TYPE VARCHAR(20)'))
            changed = True

    invite_columns = (
        {col['name'] for col in inspector.get_columns('club_invites')}
        if 'club_invites' in inspector.get_table_names() else set()
    )
    if invite_columns and 'membership_expires_on' not in invite_columns:
        db.session.execute(text('ALTER TABLE club_invites ADD COLUMN membership_expires_on DATE'))
        changed = True

    ride_columns = {col['name'] for col in inspector.get_columns('rides')} if 'rides' in inspector.get_table_names() else set()
    if ride_columns and 'garmin_groupride_code' not in ride_columns:
        db.session.execute(text('ALTER TABLE rides ADD COLUMN garmin_groupride_code VARCHAR(6)'))
        changed = True

    if 'admin_audit_logs' not in inspector.get_table_names():
        from .models import AdminAuditLog
        AdminAuditLog.__table__.create(db.engine, checkfirst=True)
        changed = True

    if 'site_feedback' not in inspector.get_table_names():
        from .models import SiteFeedback
        SiteFeedback.__table__.create(db.engine, checkfirst=True)
        changed = True

    if 'email_delivery_logs' not in inspector.get_table_names():
        from .models import EmailDeliveryLog
        EmailDeliveryLog.__table__.create(db.engine, checkfirst=True)
        changed = True

    if 'club_ownership_transfers' not in inspector.get_table_names():
        from .models import ClubOwnershipTransfer
        ClubOwnershipTransfer.__table__.create(db.engine, checkfirst=True)
        changed = True

    superadmin_emails = _configured_superadmin_emails()
    if superadmin_emails:
        from .models import User
        users = User.query.filter(User.email.in_(superadmin_emails)).all()
        for user in users:
            if not user.is_admin:
                user.is_admin = True
                changed = True

    if changed:
        db.session.commit()
