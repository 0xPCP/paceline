"""Ride poll routes — create, vote, and finalize polls for upcoming rides."""
import re
from datetime import datetime, timezone, time as dtime

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user

from ..extensions import db
from ..models import Club, ClubMembership, RidePoll, RidePollOption, RidePollVote, Ride, User

polls_bp = Blueprint('polls', __name__)

CATEGORY_LABELS = {
    'length':     'Ride Length',
    'course':     'Course / Route',
    'start_time': 'Start Time',
}

RIDE_TYPE_CHOICES = [
    ('road', 'Road'), ('gravel', 'Gravel'), ('social', 'Social'),
    ('training', 'Training'), ('event', 'Event'), ('night', 'Night'),
]


def _get_club_or_404(slug):
    return Club.query.filter_by(slug=slug).first_or_404()


def _require_member(club):
    if not current_user.is_authenticated or not current_user.is_active_member_of(club):
        abort(403)


def _require_ride_manager(club):
    if not current_user.is_authenticated or not current_user.can_manage_rides(club):
        abort(403)


def _parse_time(value):
    value = value.strip().upper()
    for fmt in ('%I:%M %p', '%I:%M%p', '%H:%M', '%I %p'):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    return None


def _parse_distance(value):
    m = re.search(r'[\d.]+', value)
    return float(m.group()) if m else None


def _active_members(club):
    return (ClubMembership.query
            .filter_by(club_id=club.id, status='active')
            .join(ClubMembership.user)
            .order_by(User.username)
            .all())


# ── Create poll ───────────────────────────────────────────────────────────────
# Entry point: linked from admin/club_rides.html

@polls_bp.route('/clubs/<slug>/polls/create', methods=['GET', 'POST'])
@login_required
def create(slug):
    club = _get_club_or_404(slug)
    _require_ride_manager(club)
    members = _active_members(club)

    if request.method == 'POST':
        # ── Core poll fields ──────────────────────────────────────────
        title            = request.form.get('title', '').strip()
        description      = request.form.get('description', '').strip() or None
        ride_date_str    = request.form.get('ride_date', '')
        pace_category    = request.form.get('pace_category', '') or None
        meeting_location = request.form.get('meeting_location', '').strip() or None
        ride_type        = request.form.get('ride_type', '') or None
        closes_at_str    = request.form.get('closes_at', '')
        finalize_mode    = request.form.get('finalize_mode', 'manual')
        poll_length      = bool(request.form.get('poll_length'))
        poll_course      = bool(request.form.get('poll_course'))
        poll_start_time  = bool(request.form.get('poll_start_time'))

        # ── Ride fields (conditionally required) ──────────────────────
        time_str         = request.form.get('start_time', '').strip()
        distance_str     = request.form.get('distance_miles', '').strip()
        elevation_str    = request.form.get('elevation_feet', '').strip()
        route_url_raw    = request.form.get('route_url', '').strip() or None
        video_url_raw    = request.form.get('video_url', '').strip() or None
        garmin_code      = (request.form.get('garmin_groupride_code', '').strip() or None)
        max_riders_str   = request.form.get('max_riders', '').strip()

        # Leader
        leader_id_raw = request.form.get('leader_id', type=int)
        leader_id = None
        ride_leader_text = None
        if leader_id_raw:
            m = ClubMembership.query.filter_by(user_id=leader_id_raw, club_id=club.id, status='active').first()
            if m:
                leader_id = leader_id_raw
                ride_leader_text = m.user.username
        if not leader_id:
            ride_leader_text = request.form.get('ride_leader_text', '').strip() or None

        errors = []
        ride_date = closes_at = None
        default_start_time = distance = elevation = max_riders = None

        if not title:
            errors.append('Poll title is required.')
        if not (poll_length or poll_course or poll_start_time):
            errors.append('Select at least one category to poll on.')

        try:
            ride_date = datetime.strptime(ride_date_str, '%Y-%m-%d').date()
        except ValueError:
            errors.append('Ride date is required.')

        try:
            closes_at = datetime.strptime(closes_at_str, '%Y-%m-%dT%H:%M')
            if closes_at <= datetime.now():
                errors.append('Poll closing time must be in the future.')
        except ValueError:
            errors.append('Poll closing time is required.')

        # Time required only if not polling on it
        if not poll_start_time:
            if not time_str:
                errors.append('Start time is required (or poll members on it).')
            else:
                default_start_time = _parse_time(time_str)
                if not default_start_time:
                    try:
                        default_start_time = datetime.strptime(time_str, '%H:%M').time()
                    except ValueError:
                        errors.append('Invalid start time format.')

        # Distance required only if not polling on it
        if not poll_length:
            if not distance_str:
                errors.append('Distance is required (or poll members on it).')
            else:
                try:
                    distance = float(distance_str)
                    if distance <= 0:
                        raise ValueError
                except ValueError:
                    errors.append('Distance must be a positive number.')

        if elevation_str:
            try:
                elevation = int(elevation_str)
            except ValueError:
                errors.append('Elevation must be a whole number.')

        if max_riders_str:
            try:
                max_riders = int(max_riders_str)
                if max_riders < 1:
                    raise ValueError
            except ValueError:
                errors.append('Max riders must be a positive whole number.')

        # Options for each polled category
        all_options = {}
        for cat in ('length', 'course', 'start_time'):
            vals = [v.strip() for v in request.form.getlist(f'{cat}_options[]') if v.strip()]
            all_options[cat] = vals[:10]

        if poll_length and not all_options['length']:
            errors.append('Add at least one length option.')
        if poll_course and not all_options['course']:
            errors.append('Add at least one course / route option.')
        if poll_start_time and not all_options['start_time']:
            errors.append('Add at least one start time option.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('clubs/poll_create.html', club=club,
                                   members=members, f=request.form)

        poll = RidePoll(
            club_id=club.id,
            created_by_id=current_user.id,
            title=title,
            description=description,
            ride_date=ride_date,
            default_start_time=default_start_time,
            pace_category=pace_category,
            meeting_location=meeting_location,
            ride_type=ride_type,
            elevation_feet=elevation,
            distance_miles=distance if not poll_length else None,
            leader_id=leader_id,
            ride_leader=ride_leader_text,
            max_riders=max_riders,
            route_url=route_url_raw if not poll_course else None,
            video_url=video_url_raw,
            garmin_groupride_code=garmin_code,
            closes_at=closes_at,
            finalize_mode=finalize_mode,
            poll_length=poll_length,
            poll_course=poll_course,
            poll_start_time=poll_start_time,
        )
        db.session.add(poll)
        db.session.flush()

        order = 0
        active_flags = {'length': poll_length, 'course': poll_course, 'start_time': poll_start_time}
        for cat, vals in all_options.items():
            if not active_flags[cat]:
                continue
            for val in vals:
                db.session.add(RidePollOption(
                    poll_id=poll.id, category=cat, value=val, display_order=order,
                ))
                order += 1

        db.session.commit()
        flash('Poll created! Members will see it in upcoming rides.', 'success')
        return redirect(url_for('polls.detail', slug=club.slug, poll_id=poll.id))

    return render_template('clubs/poll_create.html', club=club, members=members, f={})


# ── Poll detail / vote ────────────────────────────────────────────────────────

@polls_bp.route('/clubs/<slug>/polls/<int:poll_id>/')
@login_required
def detail(slug, poll_id):
    club = _get_club_or_404(slug)
    if not current_user.is_active_member_of(club):
        flash('You must be a member of this club to view ride polls.', 'warning')
        return redirect(url_for('clubs.home', slug=club.slug))

    poll = RidePoll.query.filter_by(id=poll_id, club_id=club.id).first_or_404()
    cat_data = _build_cat_data(poll, current_user.id)
    can_manage = current_user.can_manage_rides(club)

    return render_template('clubs/poll_detail.html',
                           club=club, poll=poll,
                           cat_data=cat_data,
                           cat_labels=CATEGORY_LABELS,
                           can_manage=can_manage)


@polls_bp.route('/clubs/<slug>/polls/<int:poll_id>/vote', methods=['POST'])
@login_required
def vote(slug, poll_id):
    club = _get_club_or_404(slug)
    _require_member(club)

    poll = RidePoll.query.filter_by(id=poll_id, club_id=club.id).first_or_404()
    if not poll.is_open:
        flash('This poll is no longer accepting votes.', 'warning')
        return redirect(url_for('polls.detail', slug=club.slug, poll_id=poll_id))

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    changed = False
    active = {'length': poll.poll_length, 'course': poll.poll_course, 'start_time': poll.poll_start_time}

    for cat, enabled in active.items():
        if not enabled:
            continue
        raw = request.form.get(f'vote_{cat}')
        if not raw:
            continue
        try:
            selected_id = int(raw)
        except ValueError:
            continue

        option = RidePollOption.query.filter_by(id=selected_id, poll_id=poll.id, category=cat).first()
        if not option:
            continue

        existing = RidePollVote.query.filter_by(
            poll_id=poll.id, user_id=current_user.id, category=cat,
        ).first()

        if existing:
            if existing.option_id == selected_id:
                continue
            existing.option_id = selected_id
            existing.voted_at = now
        else:
            db.session.add(RidePollVote(
                poll_id=poll.id, option_id=selected_id,
                user_id=current_user.id, category=cat, voted_at=now,
            ))

        if option.first_voted_at is None:
            option.first_voted_at = now
        changed = True

    if changed:
        db.session.commit()
        flash('Your vote has been recorded.', 'success')

    return redirect(url_for('polls.detail', slug=club.slug, poll_id=poll_id))


# ── Manage poll ───────────────────────────────────────────────────────────────

@polls_bp.route('/clubs/<slug>/polls/<int:poll_id>/close', methods=['POST'])
@login_required
def close_poll(slug, poll_id):
    club = _get_club_or_404(slug)
    _require_ride_manager(club)

    poll = RidePoll.query.filter_by(id=poll_id, club_id=club.id).first_or_404()
    if poll.status != 'open':
        flash('Poll is already closed.', 'info')
        return redirect(url_for('polls.detail', slug=club.slug, poll_id=poll_id))

    poll.status = 'closed'
    db.session.commit()

    if poll.finalize_mode == 'auto':
        _auto_finalize_poll(poll, club)
        flash('Poll closed and ride created automatically!', 'success')
        if poll.ride_id:
            return redirect(url_for('clubs.ride_detail', slug=club.slug, ride_id=poll.ride_id))
    else:
        from ..email import send_poll_closed_leader
        send_poll_closed_leader(poll)
        flash('Poll closed. Check your email for results — then finalize the ride.', 'success')

    return redirect(url_for('polls.detail', slug=club.slug, poll_id=poll_id))


@polls_bp.route('/clubs/<slug>/polls/<int:poll_id>/finalize', methods=['GET', 'POST'])
@login_required
def finalize(slug, poll_id):
    club = _get_club_or_404(slug)
    _require_ride_manager(club)

    poll = RidePoll.query.filter_by(id=poll_id, club_id=club.id).first_or_404()

    if poll.status == 'finalized':
        flash('Poll has already been finalized.', 'info')
        return redirect(url_for('polls.detail', slug=club.slug, poll_id=poll_id))
    if poll.status == 'open':
        flash('Close the poll before finalizing.', 'warning')
        return redirect(url_for('polls.detail', slug=club.slug, poll_id=poll_id))

    if request.method == 'POST':
        _do_finalize(poll, club, request.form)
        flash('Ride created! Participants have been notified.', 'success')
        return redirect(url_for('clubs.ride_detail', slug=club.slug, ride_id=poll.ride_id))

    cat_data = {}
    for cat in poll.active_categories:
        opts = poll.options_for(cat)
        cat_data[cat] = {'options': opts, 'winner': poll.winner_for(cat)}

    return render_template('clubs/poll_finalize.html',
                           club=club, poll=poll,
                           cat_data=cat_data,
                           cat_labels=CATEGORY_LABELS)


@polls_bp.route('/clubs/<slug>/polls/<int:poll_id>/delete', methods=['POST'])
@login_required
def delete_poll(slug, poll_id):
    club = _get_club_or_404(slug)
    _require_ride_manager(club)

    poll = RidePoll.query.filter_by(id=poll_id, club_id=club.id).first_or_404()
    if poll.votes:
        flash('Cannot delete a poll that has received votes.', 'danger')
        return redirect(url_for('polls.detail', slug=club.slug, poll_id=poll_id))

    db.session.delete(poll)
    db.session.commit()
    flash('Poll deleted.', 'success')
    return redirect(url_for('admin.club_rides', slug=club.slug))


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_cat_data(poll, user_id):
    data = {}
    for cat in poll.active_categories:
        opts = poll.options_for(cat)
        total = sum(o.vote_count for o in opts)
        vote = poll.user_vote_for(user_id, cat)
        data[cat] = {
            'options': opts,
            'total_votes': total,
            'user_voted_option_id': vote.option_id if vote else None,
        }
    return data


def _auto_finalize_poll(poll, club):
    form_data = {}
    for cat in poll.active_categories:
        winner = poll.winner_for(cat)
        if winner:
            form_data[f'winner_{cat}'] = str(winner.id)
    _do_finalize(poll, club, form_data)


def _do_finalize(poll, club, form_data):
    """Resolve poll winners, create a Ride from all stored + winning fields, notify voters."""
    # Start from the fixed fields stored on the poll
    start_time  = poll.default_start_time or dtime(7, 0)
    distance    = poll.distance_miles or 20.0
    route_url   = poll.route_url
    desc_parts  = []

    if poll.poll_length:
        opt = _get_winner_opt(form_data.get('winner_length'))
        if opt:
            parsed = _parse_distance(opt.value)
            if parsed:
                distance = parsed
            desc_parts.append(f'Length: {opt.value}')

    if poll.poll_course:
        opt = _get_winner_opt(form_data.get('winner_course'))
        if opt:
            if opt.value.startswith('http'):
                route_url = opt.value
            else:
                desc_parts.append(f'Course: {opt.value}')

    if poll.poll_start_time:
        opt = _get_winner_opt(form_data.get('winner_start_time'))
        if opt:
            parsed = _parse_time(opt.value)
            if parsed:
                start_time = parsed
            desc_parts.append(f'Start: {opt.value}')

    base_desc = poll.description or ''
    if desc_parts:
        poll_note = 'Poll results — ' + ', '.join(desc_parts) + '.'
        description = (base_desc + '\n\n' + poll_note).strip() if base_desc else poll_note
    else:
        description = base_desc or None

    ride = Ride(
        club_id=club.id,
        title=poll.title,
        date=poll.ride_date,
        time=start_time,
        distance_miles=distance,
        elevation_feet=poll.elevation_feet,
        pace_category=poll.pace_category or 'B',
        ride_type=poll.ride_type,
        meeting_location=poll.meeting_location,
        route_url=route_url,
        video_url=poll.video_url,
        garmin_groupride_code=poll.garmin_groupride_code,
        max_riders=poll.max_riders,
        leader_id=poll.leader_id,
        ride_leader=poll.ride_leader,
        description=description,
        created_by=poll.created_by_id,
    )
    db.session.add(ride)
    db.session.flush()

    poll.ride_id = ride.id
    poll.status  = 'finalized'
    db.session.commit()

    from ..email import send_poll_finalized
    send_poll_finalized(poll, ride)


def _get_winner_opt(id_str):
    if not id_str:
        return None
    try:
        return db.session.get(RidePollOption, int(id_str))
    except (ValueError, TypeError):
        return None
