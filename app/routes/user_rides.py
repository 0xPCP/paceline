"""User-owned ride routes.

Users can create up to 7 personal rides per calendar week.
Rides are either public (anyone can join) or private (invite-only with request-access flow).
"""
import re
from datetime import date
from flask import (
    Blueprint, render_template, redirect, url_for, flash,
    abort, request, current_app,
)
from flask_login import login_required, current_user, fresh_login_required
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Ride, RideSignup, User, UserRideInvite
from ..forms import UserRideForm, UserRideInviteForm

user_rides_bp = Blueprint('user_rides', __name__)

MAX_RIDES_PER_WEEK = 7


def _get_own_ride_or_404(ride_id):
    ride = Ride.query.filter_by(id=ride_id, owner_id=current_user.id).first_or_404()
    return ride


def _access_level(ride):
    """Return the access level of current_user for a user-owned ride."""
    if not ride.owner_id:
        return 'public'
    if current_user.is_authenticated and ride.owner_id == current_user.id:
        return 'owner'
    if not ride.is_private:
        return 'public'
    # Private ride — check invite table
    if current_user.is_authenticated:
        inv = UserRideInvite.query.filter_by(
            ride_id=ride.id, user_id=current_user.id).first()
        if inv:
            return inv.status  # 'invited' | 'requested' | 'accepted' | 'declined'
    return 'none'


# ── List ──────────────────────────────────────────────────────────────────────

@user_rides_bp.route('/')
@login_required
def list_rides():
    today = date.today()
    upcoming = (Ride.query
                .filter_by(owner_id=current_user.id)
                .filter(Ride.date >= today)
                .order_by(Ride.date, Ride.time)
                .all())
    past = (Ride.query
            .filter_by(owner_id=current_user.id)
            .filter(Ride.date < today)
            .order_by(Ride.date.desc(), Ride.time.desc())
            .limit(20)
            .all())
    rides_used = current_user.user_rides_this_week()
    return render_template('user_rides/list.html',
                           upcoming=upcoming, past=past,
                           rides_used=rides_used,
                           max_rides=MAX_RIDES_PER_WEEK)


# ── Create ────────────────────────────────────────────────────────────────────

@user_rides_bp.route('/create', methods=['GET', 'POST'])
@fresh_login_required
def create():
    if current_user.user_rides_this_week() >= MAX_RIDES_PER_WEEK:
        flash(f'You can only create {MAX_RIDES_PER_WEEK} rides per week.', 'warning')
        return redirect(url_for('user_rides.list_rides'))

    form = UserRideForm()
    if form.validate_on_submit():
        # Re-check quota just before saving
        if current_user.user_rides_this_week() >= MAX_RIDES_PER_WEEK:
            flash(f'You can only create {MAX_RIDES_PER_WEEK} rides per week.', 'warning')
            return redirect(url_for('user_rides.list_rides'))

        if not form.is_virtual.data and not form.meeting_location.data:
            form.meeting_location.errors.append('Meeting location is required for in-person rides.')
            return render_template('user_rides/create.html', form=form,
                                   rides_used=current_user.user_rides_this_week(),
                                   max_rides=MAX_RIDES_PER_WEEK)
        ride = Ride(
            owner_id=current_user.id,
            club_id=None,
            is_private=form.is_private.data,
            title=form.title.data,
            date=form.date.data,
            time=form.time.data,
            meeting_location=form.meeting_location.data or None,
            distance_miles=form.distance_miles.data,
            elevation_feet=form.elevation_feet.data,
            pace_category=form.pace_category.data,
            ride_type=form.ride_type.data,
            ride_leader=form.ride_leader.data or current_user.username,
            route_url=form.route_url.data or None,
            video_url=form.video_url.data or None,
            garmin_groupride_code=(form.garmin_groupride_code.data or '').strip() or None,
            description=form.description.data,
            max_riders=form.max_riders.data,
            is_virtual=form.is_virtual.data,
            virtual_platform=form.virtual_platform.data or None,
            virtual_platform_url=form.virtual_platform_url.data or None,
            created_by=current_user.id,
        )
        db.session.add(ride)
        db.session.flush()
        # Creator is automatically signed up on their own ride
        db.session.add(RideSignup(ride_id=ride.id, user_id=current_user.id))
        db.session.commit()
        flash('Ride created!', 'success')
        return redirect(url_for('user_rides.detail', ride_id=ride.id))

    return render_template('user_rides/create.html', form=form,
                           rides_used=current_user.user_rides_this_week(),
                           max_rides=MAX_RIDES_PER_WEEK)


# ── Detail ────────────────────────────────────────────────────────────────────

@user_rides_bp.route('/<int:ride_id>')
def detail(ride_id):
    ride = Ride.query.filter(
        Ride.id == ride_id, Ride.owner_id.isnot(None)
    ).first_or_404()

    access = _access_level(ride)
    invite_form = UserRideInviteForm() if access == 'owner' else None

    # Pending access requests (owner panel)
    pending_invites = []
    accepted_invites = []
    if access == 'owner':
        pending_invites = UserRideInvite.query.filter_by(
            ride_id=ride.id, status='requested').all()
        accepted_invites = UserRideInvite.query.filter_by(
            ride_id=ride.id, status='accepted').all()

    user_signup = None
    if current_user.is_authenticated:
        user_signup = RideSignup.query.filter_by(
            ride_id=ride.id, user_id=current_user.id).first()

    return render_template('user_rides/detail.html',
                           ride=ride, access=access,
                           invite_form=invite_form,
                           pending_invites=pending_invites,
                           accepted_invites=accepted_invites,
                           user_signup=user_signup)


@user_rides_bp.route('/<int:ride_id>/groupride-code', methods=['POST'])
@login_required
def groupride_code(ride_id):
    ride = Ride.query.filter(
        Ride.id == ride_id, Ride.owner_id.isnot(None)
    ).first_or_404()
    access = _access_level(ride)
    signup = RideSignup.query.filter_by(ride_id=ride.id, user_id=current_user.id).first()
    can_manage = access == 'owner'
    can_add_when_blank = (
        not ride.garmin_groupride_code
        and access in ('public', 'accepted', 'invited')
        and signup is not None
    )
    if not can_manage and not can_add_when_blank:
        abort(403)

    code = (request.form.get('garmin_groupride_code') or '').strip()
    if code and not re.fullmatch(r'\d{6}', code):
        flash('Enter the 6-digit Garmin GroupRide code.', 'danger')
        return redirect(url_for('user_rides.detail', ride_id=ride.id) + '#groupride')
    if ride.garmin_groupride_code and not can_manage:
        abort(403)

    ride.garmin_groupride_code = code or None
    db.session.commit()
    flash('Garmin GroupRide code updated.', 'success')
    return redirect(url_for('user_rides.detail', ride_id=ride.id) + '#groupride')


# ── Edit ──────────────────────────────────────────────────────────────────────

@user_rides_bp.route('/<int:ride_id>/edit', methods=['GET', 'POST'])
@fresh_login_required
def edit(ride_id):
    ride = _get_own_ride_or_404(ride_id)
    form = UserRideForm(obj=ride)
    if form.validate_on_submit():
        if not form.is_virtual.data and not form.meeting_location.data:
            form.meeting_location.errors.append('Meeting location is required for in-person rides.')
            return render_template('user_rides/create.html', form=form, ride=ride,
                                   rides_used=current_user.user_rides_this_week(),
                                   max_rides=MAX_RIDES_PER_WEEK)
        form.populate_obj(ride)
        ride.meeting_location = form.meeting_location.data or None
        if not form.route_url.data:
            ride.route_url = None
        if not form.video_url.data:
            ride.video_url = None
        ride.garmin_groupride_code = (form.garmin_groupride_code.data or '').strip() or None
        ride.virtual_platform = form.virtual_platform.data or None
        ride.virtual_platform_url = form.virtual_platform_url.data or None
        db.session.commit()
        flash('Ride updated.', 'success')
        return redirect(url_for('user_rides.detail', ride_id=ride.id))
    return render_template('user_rides/create.html', form=form, ride=ride,
                           rides_used=current_user.user_rides_this_week(),
                           max_rides=MAX_RIDES_PER_WEEK)


# ── Delete ────────────────────────────────────────────────────────────────────

@user_rides_bp.route('/<int:ride_id>/delete', methods=['POST'])
@fresh_login_required
def delete(ride_id):
    ride = _get_own_ride_or_404(ride_id)
    db.session.delete(ride)
    db.session.commit()
    flash('Ride deleted.', 'success')
    return redirect(url_for('user_rides.list_rides'))


# ── Public ride: join / leave ─────────────────────────────────────────────────

@user_rides_bp.route('/<int:ride_id>/signup', methods=['POST'])
@login_required
def signup(ride_id):
    ride = Ride.query.filter(
        Ride.id == ride_id, Ride.owner_id.isnot(None)
    ).first_or_404()

    if ride.is_private:
        flash('This is a private ride. Request access to join.', 'warning')
        return redirect(url_for('user_rides.detail', ride_id=ride.id))

    if ride.is_full:
        flash('This ride is full.', 'warning')
        return redirect(url_for('user_rides.detail', ride_id=ride.id))

    existing = RideSignup.query.filter_by(ride_id=ride.id, user_id=current_user.id).first()
    if not existing:
        is_anon = request.form.get('is_anonymous') == '1'
        db.session.add(RideSignup(ride_id=ride.id, user_id=current_user.id, is_anonymous=is_anon))
        db.session.commit()
        flash("You're signed up!", 'success')
    return redirect(url_for('user_rides.detail', ride_id=ride.id))


@user_rides_bp.route('/<int:ride_id>/unsignup', methods=['POST'])
@login_required
def unsignup(ride_id):
    ride = Ride.query.filter(
        Ride.id == ride_id, Ride.owner_id.isnot(None)
    ).first_or_404()
    if ride.owner_id == current_user.id:
        flash("You can't leave your own ride.", 'warning')
        return redirect(url_for('user_rides.detail', ride_id=ride.id))

    signup = RideSignup.query.filter_by(ride_id=ride.id, user_id=current_user.id).first()
    if signup:
        db.session.delete(signup)
        db.session.commit()
        flash('You have left the ride.', 'success')
    return redirect(url_for('user_rides.detail', ride_id=ride.id))


# ── Private ride: request access ─────────────────────────────────────────────

@user_rides_bp.route('/<int:ride_id>/request-access', methods=['POST'])
@login_required
def request_access(ride_id):
    ride = Ride.query.filter(
        Ride.id == ride_id, Ride.owner_id.isnot(None), Ride.is_private == True
    ).first_or_404()

    if ride.owner_id == current_user.id:
        return redirect(url_for('user_rides.detail', ride_id=ride.id))

    inv = UserRideInvite.query.filter_by(
        ride_id=ride.id, user_id=current_user.id).first()

    if inv:
        if inv.status == 'accepted':
            flash('You already have access to this ride.', 'info')
        elif inv.status == 'invited':
            # Auto-accept an outstanding invitation
            inv.status = 'accepted'
            if not RideSignup.query.filter_by(ride_id=ride.id, user_id=current_user.id).first():
                db.session.add(RideSignup(ride_id=ride.id, user_id=current_user.id))
            db.session.commit()
            flash('Invitation accepted! You now have access to this ride.', 'success')
        elif inv.status == 'requested':
            flash('Your request is pending — the ride creator will review it.', 'info')
        elif inv.status == 'declined':
            flash('Your previous request was declined.', 'warning')
    else:
        db.session.add(UserRideInvite(
            ride_id=ride.id, user_id=current_user.id, status='requested'))
        db.session.commit()
        flash('Access requested! The ride creator will be notified.', 'success')

    return redirect(url_for('user_rides.detail', ride_id=ride.id))


# ── Private ride: owner invites someone ──────────────────────────────────────

@user_rides_bp.route('/<int:ride_id>/invite', methods=['POST'])
@fresh_login_required
def invite(ride_id):
    ride = _get_own_ride_or_404(ride_id)
    if not ride.is_private:
        flash('You can only invite people to private rides.', 'warning')
        return redirect(url_for('user_rides.detail', ride_id=ride.id))

    form = UserRideInviteForm()
    if not form.validate_on_submit():
        flash('Please enter a username or email.', 'danger')
        return redirect(url_for('user_rides.detail', ride_id=ride.id))

    identifier = form.identifier.data.strip()
    target = (User.query.filter_by(username=identifier).first() or
              User.query.filter_by(email=identifier.lower()).first())
    if not target:
        flash(f'No user found with username or email "{identifier}".', 'danger')
        return redirect(url_for('user_rides.detail', ride_id=ride.id))

    if target.id == current_user.id:
        flash("You're already the ride creator.", 'info')
        return redirect(url_for('user_rides.detail', ride_id=ride.id))

    inv = UserRideInvite.query.filter_by(ride_id=ride.id, user_id=target.id).first()
    if inv:
        if inv.status in ('accepted', 'invited'):
            flash(f'{target.username} is already invited or accepted.', 'info')
        else:
            # Upgrade a declined/requested row to invited
            inv.status = 'invited'
            db.session.commit()
            flash(f'{target.username} has been invited.', 'success')
    else:
        db.session.add(UserRideInvite(
            ride_id=ride.id, user_id=target.id, status='invited'))
        db.session.commit()
        flash(f'{target.username} has been invited.', 'success')

    return redirect(url_for('user_rides.detail', ride_id=ride.id))


# ── Owner: approve / decline access request ──────────────────────────────────

@user_rides_bp.route('/<int:ride_id>/invites/<int:invite_id>/approve', methods=['POST'])
@fresh_login_required
def approve_invite(ride_id, invite_id):
    ride = _get_own_ride_or_404(ride_id)
    inv = UserRideInvite.query.filter_by(id=invite_id, ride_id=ride.id).first_or_404()
    inv.status = 'accepted'
    if not RideSignup.query.filter_by(ride_id=ride.id, user_id=inv.user_id).first():
        db.session.add(RideSignup(ride_id=ride.id, user_id=inv.user_id))
    db.session.commit()
    flash(f'{inv.user.username} approved.', 'success')
    return redirect(url_for('user_rides.detail', ride_id=ride.id))


@user_rides_bp.route('/<int:ride_id>/invites/<int:invite_id>/decline', methods=['POST'])
@fresh_login_required
def decline_invite(ride_id, invite_id):
    ride = _get_own_ride_or_404(ride_id)
    inv = UserRideInvite.query.filter_by(id=invite_id, ride_id=ride.id).first_or_404()
    inv.status = 'declined'
    # Remove from signups if previously approved
    signup = RideSignup.query.filter_by(ride_id=ride.id, user_id=inv.user_id).first()
    if signup:
        db.session.delete(signup)
    db.session.commit()
    flash(f'{inv.user.username} declined.', 'success')
    return redirect(url_for('user_rides.detail', ride_id=ride.id))


# ── Invitee: accept their own invitation ─────────────────────────────────────

@user_rides_bp.route('/<int:ride_id>/invites/<int:invite_id>/accept', methods=['POST'])
@login_required
def accept_invite(ride_id, invite_id):
    ride = Ride.query.filter(
        Ride.id == ride_id, Ride.owner_id.isnot(None)
    ).first_or_404()
    inv = UserRideInvite.query.filter_by(
        id=invite_id, ride_id=ride.id, user_id=current_user.id).first_or_404()

    if inv.status != 'invited':
        flash('This invitation is no longer valid.', 'warning')
        return redirect(url_for('user_rides.detail', ride_id=ride.id))

    inv.status = 'accepted'
    if not RideSignup.query.filter_by(ride_id=ride.id, user_id=current_user.id).first():
        db.session.add(RideSignup(ride_id=ride.id, user_id=current_user.id))
    db.session.commit()
    flash("You've accepted the invitation! Welcome to the ride.", 'success')
    return redirect(url_for('user_rides.detail', ride_id=ride.id))
