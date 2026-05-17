import re
import secrets
from datetime import datetime, date, timedelta, timezone
from flask_login import UserMixin
from .extensions import db, login_manager
from .security import video_embed_url
from .sports import DEFAULT_SPORT, normalize_sport, normalize_sport_preferences


@login_manager.user_loader
def load_user(user_id):
    try:
        raw_id, raw_version = str(user_id).split(':', 1)
        user_id_int = int(raw_id)
        token_version = int(raw_version)
    except (TypeError, ValueError):
        return None

    user = db.session.get(User, user_id_int, populate_existing=True)
    if user is None or user.session_token_version != token_version:
        return None
    return user


class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    username_finalized = db.Column(db.Boolean, default=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    google_sub = db.Column(db.String(255), unique=True, nullable=True)
    session_token_version = db.Column(db.Integer, default=0, nullable=False)
    mfa_enabled = db.Column(db.Boolean, default=False, nullable=False)
    mfa_secret = db.Column(db.String(64), nullable=True)
    mfa_backup_codes = db.Column(db.JSON, nullable=True)
    is_admin   = db.Column(db.Boolean, default=False, nullable=False)  # global superadmin
    is_active  = db.Column(db.Boolean, default=True,  nullable=False)  # False = account disabled
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Profile / location
    address = db.Column(db.String(500), nullable=True)
    zip_code = db.Column(db.String(10), nullable=True)
    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)

    # Emergency contact — opt-in; visible to club ride admins on ride day
    emergency_contact_name  = db.Column(db.String(100), nullable=True)
    emergency_contact_phone = db.Column(db.String(30), nullable=True)

    # Gear inventory — list of item IDs from gear.py GEAR_CATALOG
    gear_inventory = db.Column(db.JSON, nullable=True)

    # Public profile
    profile_is_public = db.Column(db.Boolean, default=False, nullable=False, server_default='false')
    gender   = db.Column(db.String(10), nullable=True)  # 'male' | 'female' | 'nonbinary'
    bio      = db.Column(db.Text, nullable=True)
    language = db.Column(db.String(5), nullable=True)   # preferred UI language code
    sport_preferences = db.Column(db.JSON, nullable=True)  # dormant multi-sport support
    email_preferences = db.Column(db.JSON, nullable=True)

    # Strava linking
    strava_id = db.Column(db.BigInteger, unique=True, nullable=True)
    strava_profile_url = db.Column(db.String(500), nullable=True)
    strava_access_token = db.Column(db.Text, nullable=True)
    strava_refresh_token = db.Column(db.Text, nullable=True)
    strava_token_expires_at = db.Column(db.Integer, nullable=True)

    signups = db.relationship('RideSignup', backref='user', lazy=True, cascade='all, delete-orphan')
    club_memberships = db.relationship('ClubMembership', backref='user', lazy=True,
                                       cascade='all, delete-orphan',
                                       foreign_keys='ClubMembership.user_id')
    club_admin_roles = db.relationship('ClubAdmin', backref='user', lazy=True, cascade='all, delete-orphan')
    waiver_signatures = db.relationship('WaiverSignature', backref='user', lazy=True, cascade='all, delete-orphan')

    def get_id(self):
        return f'{self.id}:{self.session_token_version or 0}'

    def revoke_sessions(self):
        self.session_token_version = (self.session_token_version or 0) + 1

    def is_club_admin(self, club):
        """Full club admin: can manage settings, members, and rides."""
        if self.is_admin:
            return True
        if getattr(club, 'owner_id', None) == self.id:
            return True
        row = ClubAdmin.query.filter_by(user_id=self.id, club_id=club.id).first()
        return row is not None and row.role == 'admin'

    def is_ride_manager(self, club):
        """Ride-only manager: can add/edit/cancel rides but not club settings."""
        row = ClubAdmin.query.filter_by(user_id=self.id, club_id=club.id).first()
        return row is not None and row.role == 'ride_manager'

    def can_manage_rides(self, club):
        return self.is_club_admin(club) or self.is_ride_manager(club)

    def is_member_of(self, club):
        """True for any membership record (active or pending)."""
        return ClubMembership.query.filter_by(user_id=self.id, club_id=club.id).first() is not None

    def is_active_member_of(self, club):
        """True only if the membership is approved/active."""
        row = ClubMembership.query.filter_by(user_id=self.id, club_id=club.id).first()
        return (
            row is not None
            and row.status == 'active'
            and (row.dues_paid_until is None or row.dues_paid_until >= date.today())
        )

    def is_pending_member_of(self, club):
        """True if the user has requested to join but is awaiting admin approval."""
        row = ClubMembership.query.filter_by(user_id=self.id, club_id=club.id).first()
        return row is not None and row.status == 'pending'

    def is_pending_payment_member_of(self, club):
        """True if the user joined but still needs club-admin dues confirmation."""
        row = ClubMembership.query.filter_by(user_id=self.id, club_id=club.id).first()
        return row is not None and row.status == 'pending_payment'

    def is_content_editor(self, club):
        """Can manage news posts and club description only."""
        row = ClubAdmin.query.filter_by(user_id=self.id, club_id=club.id).first()
        return row is not None and row.role == 'content_editor'

    def is_treasurer(self, club):
        """Can view/export member data."""
        row = ClubAdmin.query.filter_by(user_id=self.id, club_id=club.id).first()
        return row is not None and row.role == 'treasurer'

    def can_manage_content(self, club):
        return self.is_club_admin(club) or self.is_content_editor(club)

    def can_view_members(self, club):
        return self.is_club_admin(club) or self.is_treasurer(club)

    def has_signed_waiver(self, club, year=None):  # year param kept for call-site compat
        waiver = club.current_waiver
        if waiver is None:
            return True  # club has no waiver, nothing to sign
        return WaiverSignature.query.filter_by(
            user_id=self.id, waiver_id=waiver.id
        ).first() is not None

    @property
    def preferred_sports(self):
        return normalize_sport_preferences(self.sport_preferences)

    def prefers_sport(self, sport):
        return normalize_sport(sport) in self.preferred_sports

    def set_sport_preferences(self, sports):
        self.sport_preferences = normalize_sport_preferences(sports)

    def user_rides_this_week(self):
        """Count of user-owned rides in the current calendar week (Mon–Sun)."""
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        return Ride.query.filter(
            Ride.owner_id == self.id,
            Ride.date >= week_start,
            Ride.date <= week_end,
        ).count()

    def friend_status(self, other_user):
        """Return 'none' | 'pending_sent' | 'pending_received' | 'accepted' | 'declined'."""
        row = UserFriend.query.filter(
            db.or_(
                db.and_(UserFriend.requester_id == self.id, UserFriend.addressee_id == other_user.id),
                db.and_(UserFriend.requester_id == other_user.id, UserFriend.addressee_id == self.id),
            )
        ).first()
        if not row:
            return 'none'
        if row.status == 'accepted':
            return 'accepted'
        if row.status == 'pending':
            return 'pending_sent' if row.requester_id == self.id else 'pending_received'
        return 'declined'

    def friend_request_row(self, other_user):
        """Return the UserFriend row between self and other_user, or None."""
        return UserFriend.query.filter(
            db.or_(
                db.and_(UserFriend.requester_id == self.id, UserFriend.addressee_id == other_user.id),
                db.and_(UserFriend.requester_id == other_user.id, UserFriend.addressee_id == self.id),
            )
        ).first()

    def accepted_friend_ids(self):
        """Return set of user IDs who are accepted friends."""
        rows = UserFriend.query.filter(
            db.or_(
                db.and_(UserFriend.requester_id == self.id, UserFriend.status == 'accepted'),
                db.and_(UserFriend.addressee_id == self.id, UserFriend.status == 'accepted'),
            )
        ).all()
        return {
            r.addressee_id if r.requester_id == self.id else r.requester_id
            for r in rows
        }


class Club(db.Model):
    __tablename__ = 'clubs'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(80), unique=True, nullable=False)  # URL-safe identifier
    name = db.Column(db.String(200), nullable=False)
    tagline = db.Column(db.String(200), nullable=True)
    description = db.Column(db.Text, nullable=True)
    logo_url = db.Column(db.String(500), nullable=True)
    logo_key = db.Column(db.String(500), nullable=True)  # storage key for uploaded logo
    website = db.Column(db.String(500), nullable=True)
    contact_email = db.Column(db.String(255), nullable=True)
    address = db.Column(db.String(500), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    state = db.Column(db.String(50), nullable=True)
    zip_code = db.Column(db.String(10), nullable=True)
    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    sport_type = db.Column(db.String(20), default=DEFAULT_SPORT, nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Club theming
    theme_primary = db.Column(db.String(7), nullable=True)   # hex e.g. "#2d6a4f"
    theme_accent  = db.Column(db.String(7), nullable=True)   # hex e.g. "#e76f51"
    banner_url    = db.Column(db.String(500), nullable=True)  # header background image

    # Hosting mode: 'full' (complete club platform) or 'rides_only' (ride calendar only)
    hosting_mode = db.Column(db.String(20), default='full', nullable=False)

    # Visibility
    is_hidden = db.Column(db.Boolean, default=True, nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    is_featured = db.Column(db.Boolean, default=False, nullable=False)
    featured_rank = db.Column(db.Integer, nullable=True)

    # Privacy
    is_private = db.Column(db.Boolean, default=False, nullable=False)

    # Membership settings
    require_membership = db.Column(db.Boolean, default=False, nullable=False)  # must join before ride signup
    join_approval = db.Column(db.String(10), default='auto', nullable=False)   # 'auto' | 'manual'
    membership_dues_required = db.Column(db.Boolean, default=False, nullable=False)
    membership_dues_mode = db.Column(db.String(20), default='manual', nullable=False)
    membership_dues_url = db.Column(db.String(500), nullable=True)
    membership_dues_amount_cents = db.Column(db.Integer, nullable=True)
    membership_dues_currency = db.Column(db.String(3), default='usd', nullable=False)
    membership_duration_months = db.Column(db.Integer, default=12, nullable=False)
    stripe_account_id = db.Column(db.String(255), nullable=True)
    stripe_account_connected_at = db.Column(db.DateTime, nullable=True)

    # Strava integration
    strava_club_id = db.Column(db.BigInteger, nullable=True)  # numeric Strava club ID

    # Theme preset identifier (matches THEME_PRESETS in routes/clubs.py), or 'custom'
    theme_preset = db.Column(db.String(30), nullable=True)

    # Social media / communication
    facebook_url     = db.Column(db.String(500), nullable=True)
    instagram_url    = db.Column(db.String(500), nullable=True)
    twitter_url      = db.Column(db.String(500), nullable=True)
    newsletter_url   = db.Column(db.String(500), nullable=True)

    # Governance / resources
    bylaws_url          = db.Column(db.String(500), nullable=True)
    safety_guidelines   = db.Column(db.Text, nullable=True)

    # Weather-based auto-cancel thresholds
    auto_cancel_enabled  = db.Column(db.Boolean, default=False, nullable=False)
    cancel_rain_prob     = db.Column(db.Integer, default=80, nullable=False)   # % precip probability
    cancel_wind_mph      = db.Column(db.Integer, default=35, nullable=False)   # mph
    cancel_temp_min_f    = db.Column(db.Integer, default=28, nullable=False)   # °F floor
    cancel_temp_max_f    = db.Column(db.Integer, default=100, nullable=False)  # °F ceiling

    rides = db.relationship('Ride', backref='club', lazy=True, cascade='all, delete-orphan')
    memberships = db.relationship('ClubMembership', backref='club', lazy=True, cascade='all, delete-orphan')
    admin_roles = db.relationship('ClubAdmin', backref='club', lazy=True, cascade='all, delete-orphan')
    waivers = db.relationship('ClubWaiver', backref='club', lazy=True, cascade='all, delete-orphan')
    posts = db.relationship('ClubPost', backref='club', lazy=True,
                            order_by='ClubPost.published_at.desc()', cascade='all, delete-orphan')
    leaders = db.relationship('ClubLeader', backref='club', lazy=True,
                              order_by='ClubLeader.display_order.asc()', cascade='all, delete-orphan')
    sponsors = db.relationship('ClubSponsor', backref='club', lazy=True,
                               order_by='ClubSponsor.display_order.asc()', cascade='all, delete-orphan')
    owner = db.relationship('User', foreign_keys=[owner_id])

    @property
    def member_count(self):
        return ClubMembership.query.filter(
            ClubMembership.club_id == self.id,
            ClubMembership.status == 'active',
            db.or_(ClubMembership.dues_paid_until == None, ClubMembership.dues_paid_until >= date.today()),
        ).count()

    @property
    def normalized_sport_type(self):
        return normalize_sport(self.sport_type)

    @property
    def current_waiver(self):
        """Most recently created waiver for this club."""
        return (ClubWaiver.query
                .filter_by(club_id=self.id)
                .order_by(ClubWaiver.created_at.desc())
                .first())

    @property
    def stripe_dues_ready(self):
        return bool(
            self.membership_dues_mode == 'stripe_connect'
            and self.stripe_account_id
            and self.stripe_account_connected_at
            and self.membership_dues_amount_cents
        )

    @property
    def membership_dues_amount_display(self):
        if not self.membership_dues_amount_cents:
            return ''
        return f'{self.membership_dues_amount_cents / 100:.2f}'

    @property
    def effective_owner(self):
        if self.owner:
            return self.owner
        admin_row = (ClubAdmin.query
                     .filter_by(club_id=self.id, role='admin')
                     .order_by(ClubAdmin.granted_at.asc(), ClubAdmin.id.asc())
                     .first())
        return admin_row.user if admin_row else None


class ClubMembership(db.Model):
    """User subscribing/favoriting a club."""
    __tablename__ = 'club_memberships'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=False)
    status = db.Column(db.String(20), default='active', nullable=False)  # 'active' | 'pending' | 'pending_payment'
    joined_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    dues_paid_until = db.Column(db.Date, nullable=True)
    dues_confirmed_at = db.Column(db.DateTime, nullable=True)
    dues_confirmed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    dues_confirmed_by = db.relationship('User', foreign_keys=[dues_confirmed_by_id])

    __table_args__ = (db.UniqueConstraint('user_id', 'club_id', name='uq_membership'),)


class ClubMembershipPayment(db.Model):
    """Tracks automated dues payments created through Stripe Connect."""
    __tablename__ = 'club_membership_payments'

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    membership_id = db.Column(db.Integer, db.ForeignKey('club_memberships.id'), nullable=False)
    provider = db.Column(db.String(20), default='stripe', nullable=False)
    provider_session_id = db.Column(db.String(255), unique=True, nullable=True)
    provider_payment_intent_id = db.Column(db.String(255), nullable=True)
    amount_cents = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(3), default='usd', nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    paid_at = db.Column(db.DateTime, nullable=True)

    club = db.relationship('Club')
    user = db.relationship('User')
    membership = db.relationship('ClubMembership')


class ClubAdmin(db.Model):
    """Grants a user admin rights over a specific club."""
    __tablename__ = 'club_admins'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=False)
    granted_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    role = db.Column(db.String(20), default='admin', nullable=False)  # 'admin' | 'ride_manager'

    __table_args__ = (db.UniqueConstraint('user_id', 'club_id', name='uq_club_admin'),)


class ClubOwnershipTransfer(db.Model):
    """Pending club ownership transfer that must be accepted by the new owner."""
    __tablename__ = 'club_ownership_transfers'

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=False)
    from_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    to_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token = db.Column(db.String(96), unique=True, nullable=False,
                      default=lambda: secrets.token_urlsafe(48))
    status = db.Column(db.String(20), default='pending', nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc) + timedelta(days=7),
        nullable=False,
    )
    accepted_at = db.Column(db.DateTime, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)

    club = db.relationship('Club', foreign_keys=[club_id])
    from_user = db.relationship('User', foreign_keys=[from_user_id])
    to_user = db.relationship('User', foreign_keys=[to_user_id])

    @property
    def is_expired(self):
        expires = self.expires_at.replace(tzinfo=None) if self.expires_at.tzinfo else self.expires_at
        return expires < datetime.now(timezone.utc).replace(tzinfo=None)


class ClubWaiver(db.Model):
    """Waiver/rules text for a club. Multiple versions per year are allowed."""
    __tablename__ = 'club_waivers'

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    signatures = db.relationship('WaiverSignature', backref='waiver', lazy=True)


class ClubPost(db.Model):
    """Admin-authored news/announcement post for a club."""
    __tablename__ = 'club_posts'

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    image_key = db.Column(db.String(500), nullable=True)  # storage key for optional header image
    published_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    author = db.relationship('User', foreign_keys=[author_id])


class ClubLeader(db.Model):
    """Curated ride leader profile for a club's public roster."""
    __tablename__ = 'club_leaders'

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    bio = db.Column(db.Text, nullable=True)
    photo_url = db.Column(db.String(500), nullable=True)
    display_order = db.Column(db.Integer, default=0, nullable=False)

    user = db.relationship('User', foreign_keys=[user_id])


class ClubSponsor(db.Model):
    """Sponsor / partner shown on the club home page."""
    __tablename__ = 'club_sponsors'

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    logo_url = db.Column(db.String(500), nullable=True)
    logo_key = db.Column(db.String(500), nullable=True)   # storage key for uploaded logo
    website = db.Column(db.String(500), nullable=True)
    display_order = db.Column(db.Integer, default=0, nullable=False)


class RideMedia(db.Model):
    """Photo or video link shared by a member after a ride."""
    __tablename__ = 'ride_media'

    id = db.Column(db.Integer, primary_key=True)
    ride_id = db.Column(db.Integer, db.ForeignKey('rides.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    media_type = db.Column(db.String(20), nullable=False)  # 'photo' | 'video_link'
    file_path = db.Column(db.String(500), nullable=True)   # relative path for photos
    url = db.Column(db.String(500), nullable=True)          # for video_link type
    caption = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', foreign_keys=[user_id])

    @property
    def embed_url(self):
        """Return embeddable iframe URL for YouTube/Vimeo video links."""
        if self.media_type != 'video_link' or not self.url:
            return None
        return video_embed_url(self.url)


class RideComment(db.Model):
    """Member comment on a ride — pre/post discussion thread."""
    __tablename__ = 'ride_comments'

    id = db.Column(db.Integer, primary_key=True)
    ride_id = db.Column(db.Integer, db.ForeignKey('rides.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', foreign_keys=[user_id])


class ClubBoardPost(db.Model):
    """Member post on the club-wide board."""
    __tablename__ = 'club_board_posts'

    id         = db.Column(db.Integer, primary_key=True)
    club_id    = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=False)
    author_id  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    body       = db.Column(db.Text, nullable=True)
    is_pinned  = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    club   = db.relationship('Club', foreign_keys=[club_id])
    author = db.relationship('User', foreign_keys=[author_id])
    media     = db.relationship('ClubBoardMedia', back_populates='post',
                               cascade='all, delete-orphan', order_by='ClubBoardMedia.id')
    reactions = db.relationship('ClubBoardReaction', back_populates='post',
                                cascade='all, delete-orphan', order_by='ClubBoardReaction.id')
    replies   = db.relationship('ClubBoardReply', back_populates='post',
                                cascade='all, delete-orphan',
                                order_by='ClubBoardReply.created_at')

    @property
    def expires_at(self):
        from datetime import timedelta
        return self.created_at + timedelta(days=90)


class ClubBoardMedia(db.Model):
    """Photo attached to a club board post (max 3 per post)."""
    __tablename__ = 'club_board_media'

    id         = db.Column(db.Integer, primary_key=True)
    post_id    = db.Column(db.Integer, db.ForeignKey('club_board_posts.id'), nullable=False)
    file_path  = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    post = db.relationship('ClubBoardPost', back_populates='media')


class ClubBoardSubscription(db.Model):
    """A member's opt-in for board post email notifications."""
    __tablename__ = 'club_board_subscriptions'
    __table_args__ = (db.UniqueConstraint('club_id', 'user_id'),)

    id         = db.Column(db.Integer, primary_key=True)
    club_id    = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=False)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    club = db.relationship('Club', foreign_keys=[club_id])
    user = db.relationship('User', foreign_keys=[user_id])


class BoardDigestItem(db.Model):
    """Queued board activity for daily per-user email digests."""
    __tablename__ = 'board_digest_items'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    club_id    = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=False)
    post_id    = db.Column(db.Integer, db.ForeignKey('club_board_posts.id'), nullable=False)
    actor_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    event_type = db.Column(db.String(30), nullable=False)
    body_preview = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    sent_at    = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', foreign_keys=[user_id])
    club = db.relationship('Club', foreign_keys=[club_id])
    post = db.relationship('ClubBoardPost', foreign_keys=[post_id])
    actor = db.relationship('User', foreign_keys=[actor_id])


class ClubBoardReaction(db.Model):
    """Like or dislike on a board post."""
    __tablename__ = 'club_board_reactions'
    __table_args__ = (db.UniqueConstraint('post_id', 'user_id'),)

    id         = db.Column(db.Integer, primary_key=True)
    post_id    = db.Column(db.Integer, db.ForeignKey('club_board_posts.id'), nullable=False)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reaction   = db.Column(db.String(10), nullable=False)  # 'like' | 'dislike'
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    post = db.relationship('ClubBoardPost', back_populates='reactions')
    user = db.relationship('User', foreign_keys=[user_id])


class ClubBoardReply(db.Model):
    """Flat reply to a board post."""
    __tablename__ = 'club_board_replies'

    id         = db.Column(db.Integer, primary_key=True)
    post_id    = db.Column(db.Integer, db.ForeignKey('club_board_posts.id'), nullable=False)
    author_id  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    body       = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    post   = db.relationship('ClubBoardPost', back_populates='replies')
    author = db.relationship('User', foreign_keys=[author_id])


class ClubInvite(db.Model):
    """Time-limited invite token sent by an admin; grants immediate active membership on claim."""
    __tablename__ = 'club_invites'

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    used_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    # True = account was pre-created by bulk import; user must set a password via setup_account
    is_new_user = db.Column(db.Boolean, default=False, nullable=False)
    membership_expires_on = db.Column(db.Date, nullable=True)

    club = db.relationship('Club', foreign_keys=[club_id])
    creator = db.relationship('User', foreign_keys=[created_by])
    used_by = db.relationship('User', foreign_keys=[used_by_user_id])

    @property
    def is_expired(self):
        from datetime import datetime, timezone
        expires = self.expires_at.replace(tzinfo=None) if self.expires_at.tzinfo else self.expires_at
        return expires < datetime.now(timezone.utc).replace(tzinfo=None)


class AdminAuditLog(db.Model):
    """Records high-impact actions performed from the superadmin panel."""
    __tablename__ = 'admin_audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    action = db.Column(db.String(80), nullable=False)
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    actor = db.relationship('User', foreign_keys=[actor_id])
    target_user = db.relationship('User', foreign_keys=[target_user_id])


class SiteFeedback(db.Model):
    """Feedback submitted from public site pages for superadmin review."""
    __tablename__ = 'site_feedback'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    name = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    message = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(80), nullable=True)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    read_at = db.Column(db.DateTime, nullable=True)
    read_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = db.relationship('User', foreign_keys=[user_id])
    read_by = db.relationship('User', foreign_keys=[read_by_id])


class PlatformPost(db.Model):
    """Superadmin-authored homepage news or feature announcements."""
    __tablename__ = 'platform_posts'

    id = db.Column(db.Integer, primary_key=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    summary = db.Column(db.String(300), nullable=True)
    body = db.Column(db.Text, nullable=False)
    is_published = db.Column(db.Boolean, default=True, nullable=False)
    published_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    author = db.relationship('User', foreign_keys=[author_id])


class EmailDeliveryLog(db.Model):
    """Aggregated local telemetry for transactional email sends."""
    __tablename__ = 'email_delivery_logs'

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(30), nullable=False)
    subject = db.Column(db.String(255), nullable=True)
    recipient_count = db.Column(db.Integer, default=0, nullable=False)
    status = db.Column(db.String(20), nullable=False)  # 'sent' | 'failed'
    error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class UserEmailLog(db.Model):
    """Per-user email telemetry used for notification caps."""
    __tablename__ = 'user_email_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    notification_key = db.Column(db.String(80), nullable=False)
    subject = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='sent')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = db.relationship('User', foreign_keys=[user_id])


class SiteSetting(db.Model):
    """Small typed settings managed from the superadmin dashboard."""
    __tablename__ = 'site_settings'

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.String(500), nullable=True)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class WaiverSignature(db.Model):
    """Records that a user accepted a club's waiver for a given year."""
    __tablename__ = 'waiver_signatures'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=False)
    waiver_id = db.Column(db.Integer, db.ForeignKey('club_waivers.id'), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    signed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (db.UniqueConstraint('user_id', 'waiver_id', name='uq_signature_waiver'),)


class Ride(db.Model):
    __tablename__ = 'rides'

    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey('clubs.id'), nullable=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    is_private = db.Column(db.Boolean, default=False, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)
    meeting_location = db.Column(db.String(500), nullable=True)
    distance_miles = db.Column(db.Float, nullable=False)
    elevation_feet = db.Column(db.Integer, nullable=True)
    pace_category = db.Column(db.String(2), nullable=False)  # A, B, C, D
    ride_type = db.Column(db.String(20), nullable=True)  # road, gravel, social, training, event, night
    is_virtual = db.Column(db.Boolean, default=False, nullable=False, server_default='false')
    virtual_platform = db.Column(db.String(64), nullable=True)   # zwift, rouvy, wahoo, etc.
    virtual_platform_url = db.Column(db.String(512), nullable=True)
    leader_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    ride_leader = db.Column(db.String(100), nullable=True)  # display name cache; set from leader FK or free text
    route_url = db.Column(db.String(500), nullable=True)
    description = db.Column(db.Text, nullable=True)
    video_url = db.Column(db.String(500), nullable=True)
    garmin_groupride_code = db.Column(db.String(6), nullable=True)
    max_riders = db.Column(db.Integer, nullable=True)
    is_cancelled = db.Column(db.Boolean, default=False, nullable=False)
    cancel_reason = db.Column(db.String(500), nullable=True)
    is_recurring = db.Column(db.Boolean, default=False, nullable=False)
    recurrence_parent_id = db.Column(db.Integer, db.ForeignKey('rides.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    signups = db.relationship('RideSignup', backref='ride', lazy=True, cascade='all, delete-orphan')
    media = db.relationship('RideMedia', backref='ride', lazy=True,
                            order_by='RideMedia.created_at.asc()', cascade='all, delete-orphan')
    comments = db.relationship('RideComment', backref='ride', lazy=True,
                               order_by='RideComment.created_at.asc()', cascade='all, delete-orphan')
    leader = db.relationship('User', foreign_keys=[leader_id])
    owner = db.relationship('User', foreign_keys=[owner_id],
                            backref=db.backref('owned_rides', lazy=True))
    recurrence_instances = db.relationship(
        'Ride', foreign_keys='Ride.recurrence_parent_id',
        backref=db.backref('recurrence_parent', remote_side='Ride.id'),
        lazy=True,
    )

    @property
    def signup_count(self):
        return sum(1 for s in self.signups if not s.is_waitlist)

    @property
    def waitlist_count(self):
        return sum(1 for s in self.signups if s.is_waitlist)

    @property
    def is_full(self):
        return self.max_riders is not None and self.signup_count >= self.max_riders

    @property
    def spots_remaining(self):
        if self.max_riders is None:
            return None
        return max(0, self.max_riders - self.signup_count)

    @property
    def ridewithgps_route_id(self):
        if not self.route_url:
            return None
        match = re.search(r'ridewithgps\.com/routes/(\d+)', self.route_url)
        return match.group(1) if match else None

    @property
    def ridewithgps_embed_url(self):
        rid = self.ridewithgps_route_id
        if not rid:
            return None
        return f'https://ridewithgps.com/embeds?type=route&id={rid}&sampleGraph=true&distanceMarkers=true'

    @property
    def ridewithgps_map_image_url(self):
        rid = self.ridewithgps_route_id
        if not rid:
            return None
        return f'https://ridewithgps.com/routes/{rid}/hover_preview.png'

    @property
    def embed_url(self):
        if not self.video_url:
            return None
        return video_embed_url(self.video_url)

    @property
    def pace_label(self):
        labels = {
            'A': 'A — Fast (22+ mph)',
            'B': 'B — Moderate (18–22 mph)',
            'C': 'C — Casual (14–18 mph)',
            'D': 'D — Beginner (<14 mph)',
        }
        return labels.get(self.pace_category, self.pace_category)


class RideSignup(db.Model):
    __tablename__ = 'ride_signups'

    id = db.Column(db.Integer, primary_key=True)
    ride_id = db.Column(db.Integer, db.ForeignKey('rides.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    is_waitlist = db.Column(db.Boolean, default=False, nullable=False)
    is_anonymous = db.Column(db.Boolean, default=False, nullable=False)
    attended = db.Column(db.Boolean, nullable=True)  # None=not recorded, True=showed up, False=no-show
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (db.UniqueConstraint('ride_id', 'user_id', name='uq_ride_user'),)


class UserRideInvite(db.Model):
    """Tracks invitations and access requests for private user rides.

    status values:
      'invited'   — owner sent an explicit invitation
      'requested' — visitor found the URL and asked to attend
      'accepted'  — access confirmed (invite accepted or request approved)
      'declined'  — owner rejected an access request
    """
    __tablename__ = 'user_ride_invites'

    id = db.Column(db.Integer, primary_key=True)
    ride_id = db.Column(db.Integer, db.ForeignKey('rides.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(10), nullable=False, default='invited')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    ride = db.relationship('Ride', backref=db.backref('invites', lazy=True,
                           cascade='all, delete-orphan'))
    user = db.relationship('User', foreign_keys=[user_id])

    __table_args__ = (db.UniqueConstraint('ride_id', 'user_id', name='uq_user_ride_invite'),)


class UserFriend(db.Model):
    """Bidirectional friendship with accept/decline lifecycle.

    status: 'pending' | 'accepted' | 'declined'
    Only one row per pair: requester → addressee is the canonical direction.
    """
    __tablename__ = 'user_friends'

    id           = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    addressee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status       = db.Column(db.String(20), default='pending', nullable=False)
    created_at   = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at   = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                              onupdate=lambda: datetime.now(timezone.utc))

    requester = db.relationship('User', foreign_keys=[requester_id],
                                backref=db.backref('sent_friend_requests', lazy=True,
                                                   cascade='all, delete-orphan'))
    addressee = db.relationship('User', foreign_keys=[addressee_id],
                                backref=db.backref('received_friend_requests', lazy=True,
                                                   cascade='all, delete-orphan'))

    __table_args__ = (db.UniqueConstraint('requester_id', 'addressee_id', name='uq_friend_request'),)


class AppErrorLog(db.Model):
    """HTTP 4xx/5xx and unhandled exceptions logged for the superadmin dashboard."""
    __tablename__ = 'app_error_logs'

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    status_code = db.Column(db.Integer, nullable=False, index=True)
    method = db.Column(db.String(10), nullable=True)
    path = db.Column(db.String(500), nullable=True)
    error_type = db.Column(db.String(120), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    traceback = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    user = db.relationship('User', foreign_keys=[user_id])
