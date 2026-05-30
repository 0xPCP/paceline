from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import (
    StringField, PasswordField, BooleanField, SubmitField,
    TextAreaField, SelectField, FloatField, IntegerField, DateField, TimeField,
    DecimalField
)
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, URL, NumberRange, Regexp, ValidationError, InputRequired
from .security import is_safe_external_url
from .strava_profile import canonical_strava_profile_url


class SafeURL(URL):
    """URL validator that rejects javascript:, data:, vbscript: and any other non-http(s) scheme."""

    def __call__(self, form, field):
        if field.data:
            super().__call__(form, field)
            if not is_safe_external_url(field.data):
                raise ValidationError('Only plain http:// and https:// URLs are accepted.')


class StravaProfileURL:
    def __call__(self, form, field):
        if field.data and not canonical_strava_profile_url(field.data):
            raise ValidationError('Enter your Strava athlete profile URL, like https://www.strava.com/athletes/123456.')


class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[
        DataRequired(), Length(3, 50),
        Regexp(r'^[a-zA-Z0-9_.-]+$', message='Username may only contain letters, numbers, underscores, hyphens, and dots.'),
    ])
    email = StringField('Email Address', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    policy_ack = BooleanField('Policy acknowledgement', validators=[
        InputRequired(message='You must review and acknowledge the Privacy Policy and Data Use Policy.'),
    ])
    submit = SubmitField('Create Account')


class UsernameSetupForm(FlaskForm):
    username = StringField('Username', validators=[
        DataRequired(), Length(3, 50),
        Regexp(r'^[a-zA-Z0-9_.-]+$', message='Username may only contain letters, numbers, underscores, hyphens, and dots.'),
    ])
    policy_ack = BooleanField('Policy acknowledgement', validators=[
        InputRequired(message='You must review and acknowledge the Privacy Policy and Data Use Policy.'),
    ])
    submit = SubmitField('Save Username')


class LoginForm(FlaskForm):
    email = StringField('Email Address', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Trust this browser')
    submit = SubmitField('Sign In')


class MfaCodeForm(FlaskForm):
    code = StringField('Authentication Code', validators=[
        DataRequired(),
        Regexp(r'^[0-9 ]{6,12}$', message='Enter a 6-digit code or an 8-digit backup code.'),
    ])
    submit = SubmitField('Verify')


class DisableMfaForm(FlaskForm):
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Disable MFA')


class PasswordResetRequestForm(FlaskForm):
    email = StringField('Email Address', validators=[DataRequired(), Email()])
    submit = SubmitField('Email Reset Link')


class ProfileForm(FlaskForm):
    username = StringField('Username', validators=[
        DataRequired(), Length(3, 50),
        Regexp(r'^[a-zA-Z0-9_.-]+$', message='Username may only contain letters, numbers, underscores, hyphens, and dots.'),
    ])
    email    = StringField('Email Address', validators=[DataRequired(), Email()])
    zip_code = StringField('Zip Code', validators=[Optional(), Length(max=10)])
    gender   = SelectField('Gender', choices=[
        ('',          '— Not specified —'),
        ('male',      'Male'),
        ('female',    'Female'),
        ('nonbinary', 'Non-binary'),
    ], validators=[Optional()])
    bio      = TextAreaField('Bio', validators=[Optional(), Length(max=500)])
    strava_profile_url = StringField('Strava Profile URL', validators=[Optional(), Length(max=500), StravaProfileURL()])
    language = SelectField('Language', choices=[
        ('',   '— Auto-detect —'),
        ('en', 'English'),
        ('fr', 'Français'),
        ('es', 'Español'),
        ('it', 'Italiano'),
        ('nl', 'Nederlands'),
        ('de', 'Deutsch'),
        ('pt', 'Português'),
    ], validators=[Optional()])
    distance_unit = SelectField('Distance units', choices=[
        ('',   '— Auto-detect from zip code —'),
        ('mi', 'Miles (US)'),
        ('km', 'Kilometres (metric)'),
    ], validators=[Optional()])
    emergency_contact_name  = StringField('Emergency Contact Name', validators=[Optional(), Length(max=100)])
    emergency_contact_phone = StringField('Emergency Contact Phone', validators=[Optional(), Length(max=30)])
    notify_ride_cancellations = BooleanField('Ride cancellations')
    notify_ride_reminders = BooleanField('Morning ride reminders')
    notify_ride_waitlist = BooleanField('Waitlist promotions')
    notify_ride_updates = BooleanField('Major ride changes')
    notify_membership_updates = BooleanField('Membership approvals, rejections, and dues updates')
    notify_club_new_rides = BooleanField('New rides from my clubs')
    notify_club_news = BooleanField('Club news posts')
    notify_weekly_digest = BooleanField('Weekly club digest')
    notify_board_digest = BooleanField('Daily message board digest')
    notify_friend_ride_signup = BooleanField('When a friend signs up for a ride')
    profile_is_public = BooleanField('Make my profile visible to everyone (not just friends)')
    recommendations_enabled = BooleanField('Show personalized ride and club recommendations')
    recommendation_location_enabled = BooleanField('Use my saved location')
    recommendation_history_enabled = BooleanField('Use my ride history')
    recommendation_friend_activity_enabled = BooleanField('Use friend activity')
    dashboard_recommendations_hidden = BooleanField('Hide recommendations on my dashboard')
    submit   = SubmitField('Save Changes')


class ClubForm(FlaskForm):
    name        = StringField('Club Name', validators=[DataRequired(), Length(max=200)])
    slug        = StringField('URL Slug', validators=[DataRequired(), Length(max=80)])
    description = TextAreaField('Description', validators=[Optional()])
    city        = StringField('City', validators=[Optional(), Length(max=100)])
    state       = StringField('State', validators=[Optional(), Length(max=50)])
    zip_code    = StringField('Zip Code', validators=[Optional(), Length(max=10)])
    address     = StringField('Address', validators=[Optional(), Length(max=500)])
    contact_email = StringField('Contact Email', validators=[Optional(), Email(), Length(max=255)])
    logo_url    = StringField('Logo URL', validators=[Optional(), SafeURL(), Length(max=500)])
    is_active   = BooleanField('Active (visible to users)', default=True)
    submit      = SubmitField('Save Club')


class ClubSettingsForm(FlaskForm):
    """Club admin version — no slug, no is_active."""
    name        = StringField('Club Name', validators=[DataRequired(), Length(max=200)])
    tagline     = StringField('Club Tagline', validators=[Optional(), Length(max=200)])
    description = TextAreaField('Description', validators=[Optional()])
    city        = StringField('City', validators=[Optional(), Length(max=100)])
    state       = StringField('State', validators=[Optional(), Length(max=50)])
    zip_code    = StringField('Zip Code', validators=[Optional(), Length(max=10)])
    address     = StringField('Address', validators=[Optional(), Length(max=500)])
    contact_email = StringField('Contact Email', validators=[Optional(), Email(), Length(max=255)])
    logo_file   = FileField('Upload Logo', validators=[
        Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'webp'], 'Images only (JPEG, PNG, WebP)'),
    ])
    logo_url    = StringField('Logo URL (or upload above)', validators=[Optional(), SafeURL(), Length(max=500)])
    # Appearance / theming
    theme_primary = StringField('Primary Color', validators=[
        Optional(), Length(max=7),
        Regexp(r'^#[0-9a-fA-F]{6}$', message='Enter a valid hex color (e.g. #3a7bd5).'),
    ])
    theme_accent  = StringField('Accent / Button Color', validators=[
        Optional(), Length(max=7),
        Regexp(r'^#[0-9a-fA-F]{6}$', message='Enter a valid hex color (e.g. #e76f51).'),
    ])
    banner_url    = StringField('Banner Image URL', validators=[Optional(), SafeURL(), Length(max=500)])
    homepage_layout = SelectField('Club Homepage Layout', default='magazine', choices=[
        ('magazine',  'Magazine — balanced club story, rides, news, and sidebar info'),
        ('dashboard', 'Dashboard — rides-first layout for active weekly calendars'),
        ('newspaper', 'Newspaper — classic bulletin layout with rides and club news columns'),
    ])
    # Visibility
    is_hidden = BooleanField('Hide club from public listings')

    # Membership settings
    is_private         = BooleanField('Private Club')
    require_membership = BooleanField('Require membership to sign up for rides')
    join_approval = SelectField('Join Approval Mode', choices=[
        ('auto',   'Auto-approve — users join immediately upon request'),
        ('manual', 'Manual approval — admin must approve each request'),
    ])
    membership_dues_required = BooleanField('Require paid dues before membership becomes active')
    membership_dues_amount = DecimalField('Dues Amount (USD)',
                                         validators=[Optional(), NumberRange(min=1, max=10000)],
                                         places=2)
    membership_duration_months = IntegerField('Dues Valid For (months)',
                                             validators=[Optional(), NumberRange(min=1, max=60)],
                                             default=12)
    # Hosting mode
    hosting_mode = SelectField('Hosting Mode', choices=[
        ('full',       'Full Club — membership, waivers, news, and full admin tools'),
        ('rides_only', 'Rides Only — simplified ride calendar, no membership management'),
    ])

    # Strava integration
    strava_club_id = StringField('Strava Club ID', validators=[Optional(), Length(max=20)])
    # Social media / communication
    facebook_url   = StringField('Facebook Page URL', validators=[Optional(), SafeURL(), Length(max=500)])
    instagram_url  = StringField('Instagram URL', validators=[Optional(), SafeURL(), Length(max=500)])
    twitter_url    = StringField('Twitter / X URL', validators=[Optional(), SafeURL(), Length(max=500)])
    newsletter_url = StringField('Newsletter Sign-up URL', validators=[Optional(), SafeURL(), Length(max=500)])
    whatsapp_url   = StringField('WhatsApp Chat URL', validators=[Optional(), SafeURL(), Length(max=500)])

    # Governance / resources
    bylaws_url        = StringField('Club Bylaws URL', validators=[Optional(), SafeURL(), Length(max=500)])
    safety_guidelines = TextAreaField('Safety Guidelines', validators=[Optional()])

    # Weather auto-cancel
    auto_cancel_enabled = BooleanField('Enable weather-based auto-cancel')
    cancel_rain_prob    = IntegerField('Cancel if rain probability ≥ (%)',
                                      validators=[Optional(), NumberRange(1, 100)], default=80)
    cancel_wind_mph     = IntegerField('Cancel if wind speed ≥ (mph)',
                                      validators=[Optional(), NumberRange(1, 200)], default=35)
    cancel_temp_min_f   = IntegerField('Cancel if temperature below (°F)',
                                      validators=[Optional(), NumberRange(-60, 120)], default=28)
    cancel_temp_max_f   = IntegerField('Cancel if temperature above (°F)',
                                      validators=[Optional(), NumberRange(-60, 150)], default=100)
    submit      = SubmitField('Save Settings')


class ClubShopItemForm(FlaskForm):
    name = StringField('Item Name', validators=[DataRequired(), Length(max=120)])
    description = TextAreaField('Description', validators=[Optional(), Length(max=1000)])
    image_url = StringField('Image URL', validators=[Optional(), SafeURL(), Length(max=500)])
    price = DecimalField('Price (USD)', validators=[DataRequired(), NumberRange(min=1, max=10000)], places=2)
    is_active = BooleanField('Available for purchase', default=True)
    display_order = IntegerField('Display Order', validators=[Optional(), NumberRange(min=0, max=9999)], default=0)
    fulfillment_notes = TextAreaField('Fulfillment Notes', validators=[Optional(), Length(max=1000)])
    submit = SubmitField('Save Item')


class ClubShopSettingsForm(FlaskForm):
    shop_tax_enabled = BooleanField('Enable Stripe Tax for shop checkout')
    shop_shipping_enabled = BooleanField('Collect shipping address at checkout')
    shop_shipping_fee = DecimalField('Flat Shipping Fee (USD)',
                                     validators=[Optional(), NumberRange(min=0, max=10000)],
                                     places=2)
    shop_shipping_countries = StringField('Allowed Shipping Countries',
                                          validators=[Optional(), Length(max=255)],
                                          default='US')
    submit = SubmitField('Save Shop Settings')


class ClubCreateForm(FlaskForm):
    """Multi-step club creation wizard — submitted as a single POST."""
    name          = StringField('Club Name', validators=[DataRequired(), Length(max=200)])
    city          = StringField('City', validators=[Optional(), Length(max=100)])
    state         = StringField('State', validators=[Optional(), Length(max=50)])
    zip_code      = StringField('Zip Code', validators=[Optional(), Length(max=10)])
    is_private    = BooleanField('Private Club')
    # hosting_mode and theme_preset are written by JS, validated as strings
    hosting_mode  = StringField('Hosting Mode', validators=[Optional(), Length(max=20)])
    # theme_preset is written by JS, validated as a string
    theme_preset  = StringField('Theme Preset', validators=[Optional(), Length(max=30)])
    theme_primary = StringField('Primary Color', validators=[
        Optional(), Length(max=7),
        Regexp(r'^#[0-9a-fA-F]{6}$', message='Enter a valid hex color (e.g. #3a7bd5).'),
    ])
    theme_accent  = StringField('Accent Color', validators=[
        Optional(), Length(max=7),
        Regexp(r'^#[0-9a-fA-F]{6}$', message='Enter a valid hex color (e.g. #e76f51).'),
    ])
    tagline       = StringField('Club Tagline', validators=[Optional(), Length(max=200)])
    description   = TextAreaField('Description', validators=[Optional()])
    contact_email = StringField('Contact Email', validators=[Optional(), Email(), Length(max=255)])
    logo_url      = StringField('Logo URL', validators=[Optional(), SafeURL(), Length(max=500)])
    banner_url    = StringField('Banner Image URL', validators=[Optional(), SafeURL(), Length(max=500)])
    submit        = SubmitField('Create Club')


class ClubPostForm(FlaskForm):
    title      = StringField('Title', validators=[DataRequired(), Length(max=200)])
    body       = TextAreaField('Body', validators=[DataRequired()])
    image_file = FileField('Header Image (optional)', validators=[
        Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'webp'], 'Images only (JPEG, PNG, WebP)'),
    ])
    submit = SubmitField('Save Post')


class PlatformPostForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(max=200)])
    summary = StringField('Short Summary', validators=[Optional(), Length(max=300)])
    body = TextAreaField('Post Body', validators=[DataRequired()])
    is_published = BooleanField('Published', default=True)
    submit = SubmitField('Save Post')


class ClubLeaderForm(FlaskForm):
    bio           = StringField('One-line bio', validators=[Optional(), Length(max=200)],
                                description='e.g. "20-year club veteran, loves gravel and rain."')
    display_order = IntegerField('Display Order', validators=[Optional(), NumberRange(min=0)], default=0)
    submit        = SubmitField('Save Leader')


class ClubSponsorForm(FlaskForm):
    name          = StringField('Sponsor Name', validators=[DataRequired(), Length(max=200)])
    logo_file     = FileField('Upload Logo', validators=[
        Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'webp'], 'Images only (JPEG, PNG, WebP)'),
    ])
    logo_url      = StringField('Logo URL (or upload above)', validators=[Optional(), SafeURL(), Length(max=500)])
    website       = StringField('Website', validators=[Optional(), SafeURL(), Length(max=500)])
    display_order = IntegerField('Display Order', validators=[Optional(), NumberRange(min=0)], default=0)
    submit        = SubmitField('Save Sponsor')


class RidePhotoUploadForm(FlaskForm):
    photo = FileField('Photo', validators=[
        FileAllowed(['jpg', 'jpeg', 'png', 'webp'], 'Images only (JPEG, PNG, WebP)'),
    ])
    caption = StringField('Caption', validators=[Optional(), Length(max=300)])
    submit = SubmitField('Upload Photo')


class RideVideoLinkForm(FlaskForm):
    url = StringField('Video URL (YouTube, Strava, Vimeo)', validators=[
        DataRequired(), SafeURL(), Length(max=500),
    ])
    caption = StringField('Caption', validators=[Optional(), Length(max=300)])
    submit = SubmitField('Share Video')


class RideCommentForm(FlaskForm):
    body = TextAreaField('Comment', validators=[DataRequired(), Length(max=2000)])
    submit = SubmitField('Post Comment')


class ClubInviteForm(FlaskForm):
    email = StringField('Email Address', validators=[DataRequired(), Email(), Length(max=255)])
    submit = SubmitField('Send Invite')


class BulkImportForm(FlaskForm):
    emails = TextAreaField('Email Addresses', validators=[DataRequired()],
                           description='One email per line. Optionally add an expiration date after a comma, like rider@example.com, 2026-12-31. Max 200 per batch.')
    membership_expires_on = DateField('Membership Active Until (optional)',
                                      validators=[Optional()],
                                      description='Applies to imported active members unless a row includes its own date.')
    message = TextAreaField('Personal Message (optional)',
                            validators=[Optional(), Length(max=500)],
                            description='Included in the email sent to each person.')
    submit = SubmitField('Import Members')


class SetPasswordForm(FlaskForm):
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField('Confirm Password',
                                     validators=[DataRequired(), EqualTo('password', message='Passwords must match.')])
    submit = SubmitField('Set Password & Join Club')


class AccountSetupForm(SetPasswordForm):
    policy_ack = BooleanField('Policy acknowledgement', validators=[
        InputRequired(message='You must review and acknowledge the Privacy Policy and Data Use Policy.'),
    ])


class FeedbackForm(FlaskForm):
    name = StringField('Name', validators=[Optional(), Length(max=120)])
    email = StringField('Email Address', validators=[Optional(), Email(), Length(max=255)])
    message = TextAreaField('Feedback', validators=[DataRequired(), Length(min=5, max=2000)])
    submit = SubmitField('Send Feedback')


class ClubContactForm(FlaskForm):
    recipient_group = SelectField('Send To', choices=[
        ('managers', 'Club Manager'),
        ('managers_and_ride_leaders', 'Club Manager and Ride Leaders'),
    ], validators=[DataRequired()])
    subject = StringField('Subject', validators=[DataRequired(), Length(min=3, max=120)])
    message = TextAreaField('Message', validators=[DataRequired(), Length(min=10, max=2000)])
    submit = SubmitField('Send Message')


VIRTUAL_PLATFORM_CHOICES = [
    ('',          '— Select platform —'),
    ('zwift',     'Zwift'),
    ('rouvy',     'Rouvy'),
    ('wahoo',     'Wahoo SYSTM'),
    ('trainerroad', 'TrainerRoad'),
    ('fulgaz',    'FulGaz'),
    ('bkool',     'BKOOL'),
    ('other',     'Other'),
]


class RideForm(FlaskForm):
    title = StringField('Ride Title', validators=[DataRequired(), Length(max=200)])
    date = DateField('Date', validators=[DataRequired()])
    time = TimeField('Start Time', validators=[DataRequired()])
    is_virtual = BooleanField('Virtual ride (Zwift, Rouvy, trainer, etc.)')
    virtual_platform = SelectField('Platform', choices=VIRTUAL_PLATFORM_CHOICES, validators=[Optional()])
    virtual_platform_url = StringField('Platform Event / Join Link', validators=[Optional(), SafeURL(), Length(max=512)])
    meeting_location = StringField('Meeting Location', validators=[Optional(), Length(max=500)])
    distance_miles = FloatField('Distance (miles)', validators=[DataRequired(), NumberRange(min=0.1)])
    elevation_feet = IntegerField('Elevation Gain (feet)', validators=[Optional()])
    pace_category = SelectField('Pace Category', choices=[
        ('A', 'A — Fast (22+ mph)'),
        ('B', 'B — Moderate (18–22 mph)'),
        ('C', 'C — Casual (14–18 mph)'),
        ('D', 'D — Beginner (<14 mph)'),
    ])
    ride_type = SelectField('Ride Type', choices=[
        ('road',     'Road'),
        ('gravel',   'Gravel'),
        ('social',   'Social'),
        ('training', 'Training'),
        ('event',    'Event'),
        ('night',    'Night Ride'),
    ], default='road')
    ride_leader = StringField('Ride Leader', validators=[Optional(), Length(max=100)])
    route_url = StringField('Route URL (Strava, RideWithGPS, etc.)', validators=[Optional(), SafeURL(), Length(max=500)])
    video_url = StringField('Video URL (YouTube or Vimeo)', validators=[Optional(), SafeURL(), Length(max=500)])
    garmin_groupride_code = StringField('Garmin GroupRide Code', validators=[
        Optional(), Regexp(r'^\d{6}$', message='Enter the 6-digit Garmin GroupRide code.'),
    ])
    description = TextAreaField('Description / Notes', validators=[Optional()])
    max_riders = IntegerField('Max Riders (leave blank for unlimited)', validators=[Optional(), NumberRange(min=1, max=9999)])
    is_newbie_friendly = BooleanField('New Rider Friendly — welcoming to first-time road cyclists')
    is_cancelled = BooleanField('Mark as Cancelled')
    is_recurring = BooleanField('Repeat weekly (generates 8 weeks of instances)')
    submit = SubmitField('Save Ride')


class UserRideForm(FlaskForm):
    """Form for creating/editing a user-owned (non-club) ride."""
    title            = StringField('Ride Title', validators=[DataRequired(), Length(max=200)])
    date             = DateField('Date', validators=[DataRequired()])
    time             = TimeField('Start Time', validators=[DataRequired()])
    is_virtual       = BooleanField('Virtual ride (Zwift, Rouvy, trainer, etc.)')
    virtual_platform = SelectField('Platform', choices=VIRTUAL_PLATFORM_CHOICES, validators=[Optional()])
    virtual_platform_url = StringField('Platform Event / Join Link', validators=[Optional(), SafeURL(), Length(max=512)])
    meeting_location = StringField('Meeting Location', validators=[Optional(), Length(max=500)])
    distance_miles   = FloatField('Distance (miles)', validators=[DataRequired(), NumberRange(min=0.1)])
    elevation_feet   = IntegerField('Elevation Gain (feet)', validators=[Optional()])
    pace_category    = SelectField('Pace Category', choices=[
        ('A', 'A — Fast (22+ mph)'),
        ('B', 'B — Moderate (18–22 mph)'),
        ('C', 'C — Casual (14–18 mph)'),
        ('D', 'D — Beginner (<14 mph)'),
    ])
    ride_type = SelectField('Ride Type', choices=[
        ('road',     'Road'),
        ('gravel',   'Gravel'),
        ('social',   'Social'),
        ('training', 'Training'),
        ('event',    'Event'),
        ('night',    'Night Ride'),
    ], default='road')
    ride_leader      = StringField('Ride Leader', validators=[Optional(), Length(max=100)])
    route_url        = StringField('Route URL', validators=[Optional(), SafeURL(), Length(max=500)])
    video_url        = StringField('Video URL (YouTube or Vimeo)', validators=[Optional(), SafeURL(), Length(max=500)])
    garmin_groupride_code = StringField('Garmin GroupRide Code', validators=[
        Optional(), Regexp(r'^\d{6}$', message='Enter the 6-digit Garmin GroupRide code.'),
    ])
    description      = TextAreaField('Description / Notes', validators=[Optional()])
    max_riders       = IntegerField('Max Riders (leave blank for unlimited)', validators=[Optional(), NumberRange(min=1, max=9999)])
    is_private       = BooleanField('Private ride — only invited riders can see details')
    submit           = SubmitField('Save Ride')


class UserRideInviteForm(FlaskForm):
    identifier = StringField('Username or Email', validators=[DataRequired(), Length(max=255)])
    submit = SubmitField('Invite')
