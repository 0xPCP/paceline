"""Ride poll routes — create, vote, finalize polls for upcoming rides."""
import re
from datetime import datetime, timezone, time as dtime

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user

from ..extensions import db
from ..models import Club, RidePoll, RidePollOption, RidePollVote, Ride

polls_bp = Blueprint('polls', __name__)

CATEGORY_LABELS = {
    'length':     'Ride Length',
    'course':     'Course / Route',
    'start_time': 'Start Time',
}


def _get_club_or_404(slug):
    return Club.query.filter_by(slug=slug).first_or_404()


def _require_member(club):
    if not current_user.is_authenticated or not current_user.is_active_member_of(club):
        abort(403)


def _require_ride_manager(club):
    if not current_user.is_authenticated or not current_user.can_manage_rides(club):
        abort(403)


def _parse_time(value):
    """Try multiple formats; return time object or None."""
    value = value.strip().upper()
    for fmt in ('%I:%M %p', '%I:%M%p', '%H:%M', '%I %p'):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    return None


def _parse_distance(value):
    """Extract the leading numeric value from a string like '25 miles' → 25.0."""
    m = re.search(r'[\d.]+', value)
    return float(m.group()) if m else None


# ── Create poll ───────────────────────────────────────────────────────────────

@polls_bp.route('/clubs/<slug>/polls/create', methods=['GET', 'POST'])
@login_required
def create(slug):
    club = _get_club_or_404(slug)
    _require_ride_manager(club)

    if request.method == 'POST':
        title             = request.form.get('title', '').strip()
        description       = request.form.get('description', '').strip() or None
        ride_date_str     = request.form.get('ride_date', '')
        default_time_str  = request.form.get('default_start_time', '').strip()
        pace_category     = request.form.get('pace_category', '') or None
        meeting_location  = request.form.get('meeting_location', '').strip() or None
        closes_at_str     = request.form.get('closes_at', '')
        finalize_mode     = request.form.get('finalize_mode', 'manual')
        poll_length       = bool(request.form.get('poll_length'))
        poll_course       = bool(request.form.get('poll_course'))
        poll_start_time   = bool(request.form.get('poll_start_time'))

        errors = []
        ride_date = closes_at = default_start_time = None

        if not title:
            errors.append('Poll title is required.')
        if not (poll_length or poll_course or poll_start_time):
            errors.append('Select at least one category to poll on.')

        try:
            ride_date = datetime.strptime(ride_date_str, '%Y-%m-%d').date()
        except ValueError:
            errors.append('Invalid ride date.')

        try:
            closes_at = datetime.strptime(closes_at_str, '%Y-%m-%dT%H:%M')
            if closes_at <= datetime.now():
                errors.append('Poll closing time must be in the future.')
        except ValueError:
            errors.append('Poll closing time is required.')

        if default_time_str:
            default_start_time = _parse_time(default_time_str)

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
            return render_template('clubs/poll_create.html', club=club, f=request.form)

        poll = RidePoll(
            club_id=club.id,
            created_by_id=current_user.id,
            title=title,
            description=description,
            ride_date=ride_date,
            default_start_time=default_start_time,
            pace_category=pace_category,
            meeting_location=meeting_location,
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

    return render_template('clubs/poll_create.html', club=club, f={})


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
    return redirect(url_for('clubs.home', slug=club.slug))


# ── Finalization helpers ───────────────────────────────────────────────────────

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
    """Resolve winners, create a Ride, mark finalized, email voters."""
    start_time   = poll.default_start_time or dtime(7, 0)
    distance     = 20.0
    route_url    = None
    desc_parts   = ['Created from a ride poll.']

    if poll.poll_length:
        opt = _get_winner_opt(form_data.get('winner_length'))
        if opt:
            parsed = _parse_distance(opt.value)
            if parsed:
                distance = parsed
            desc_parts.append(f'Distance: {opt.value}')

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

    ride = Ride(
        club_id=club.id,
        title=poll.title,
        date=poll.ride_date,
        time=start_time,
        distance_miles=distance,
        pace_category=poll.pace_category or 'B',
        meeting_location=poll.meeting_location,
        route_url=route_url,
        description='\n\n'.join(desc_parts),
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
