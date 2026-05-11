import secrets
from datetime import datetime, timezone

from flask import Blueprint, abort, current_app, flash, redirect, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from ..extensions import csrf, db
from ..membership_dues import activate_membership_dues
from ..models import Club, ClubMembership, ClubMembershipPayment
from ..stripe_connect import (
    StripeConnectError,
    authorization_url,
    connect_enabled,
    create_checkout_session,
    exchange_authorization_code,
    verify_webhook_payload,
)

stripe_connect_bp = Blueprint('stripe_connect', __name__)


def _visible_club_or_404(slug):
    return Club.query.filter_by(slug=slug, is_active=True, is_hidden=False).first_or_404()


def _admin_club_or_404(slug):
    return Club.query.filter_by(slug=slug, is_active=True).first_or_404()


@stripe_connect_bp.route('/clubs/<slug>/connect')
@login_required
def connect_club(slug):
    club = _admin_club_or_404(slug)
    if not current_user.is_club_admin(club):
        abort(403)
    if not connect_enabled():
        flash('Stripe Connect is not configured for this Paceline environment yet.', 'warning')
        return redirect(url_for('admin.club_settings', slug=slug))

    state = secrets.token_urlsafe(32)
    session['stripe_connect_oauth'] = {'state': state, 'club_id': club.id}
    redirect_uri = url_for('stripe_connect.oauth_callback', _external=True)
    return redirect(authorization_url(state, redirect_uri))


@stripe_connect_bp.route('/connect/callback')
@login_required
def oauth_callback():
    pending = session.pop('stripe_connect_oauth', {}) or {}
    club = db.session.get(Club, pending.get('club_id'))
    if not club or not club.is_active:
        abort(400)
    if not current_user.is_club_admin(club):
        abort(403)
    expected_state = pending.get('state')
    if not expected_state or not secrets.compare_digest(expected_state, request.args.get('state', '')):
        abort(400)
    if request.args.get('error'):
        flash('Stripe Connect was canceled before the club account was connected.', 'warning')
        return redirect(url_for('admin.club_settings', slug=club.slug))

    code = request.args.get('code', '')
    try:
        payload = exchange_authorization_code(code)
    except StripeConnectError as exc:
        current_app.logger.warning('Stripe Connect OAuth failed for club %s: %s', club.id, exc)
        flash('Stripe could not connect this club account. Please try again.', 'danger')
        return redirect(url_for('admin.club_settings', slug=club.slug))

    stripe_account_id = payload.get('stripe_user_id')
    if not stripe_account_id:
        flash('Stripe did not return a connected account ID. Please try again.', 'danger')
        return redirect(url_for('admin.club_settings', slug=club.slug))

    club.stripe_account_id = stripe_account_id
    club.stripe_account_connected_at = datetime.now(timezone.utc)
    db.session.commit()
    flash('Stripe Connect is now linked for automated club dues.', 'success')
    return redirect(url_for('admin.club_settings', slug=club.slug))


@stripe_connect_bp.route('/clubs/<slug>/disconnect', methods=['POST'])
@login_required
def disconnect_club(slug):
    club = _admin_club_or_404(slug)
    if not current_user.is_club_admin(club):
        abort(403)
    club.stripe_account_id = None
    club.stripe_account_connected_at = None
    if club.membership_dues_mode == 'stripe_connect':
        club.membership_dues_mode = 'manual'
    db.session.commit()
    flash('Stripe Connect was disconnected. Manual dues confirmation is still available.', 'info')
    return redirect(url_for('admin.club_settings', slug=slug))


@stripe_connect_bp.route('/clubs/<slug>/checkout', methods=['POST'])
@login_required
def dues_checkout(slug):
    club = _visible_club_or_404(slug)
    if not club.membership_dues_required or not club.stripe_dues_ready:
        flash('Online dues checkout is not available for this club.', 'warning')
        return redirect(url_for('clubs.home', slug=slug))

    membership = ClubMembership.query.filter_by(user_id=current_user.id, club_id=club.id).first()
    if membership and membership.status == 'active':
        flash('Your membership is already active.', 'info')
        return redirect(url_for('clubs.home', slug=slug))
    if membership is None:
        membership = ClubMembership(user_id=current_user.id, club_id=club.id, status='pending_payment')
        db.session.add(membership)
        db.session.flush()
    else:
        membership.status = 'pending_payment'

    payment = ClubMembershipPayment(
        club_id=club.id,
        user_id=current_user.id,
        membership_id=membership.id,
        amount_cents=club.membership_dues_amount_cents,
        currency=club.membership_dues_currency or 'usd',
    )
    db.session.add(payment)
    db.session.flush()

    try:
        checkout = create_checkout_session(
            club=club,
            user=current_user,
            membership=membership,
            payment=payment,
            success_url=url_for('clubs.home', slug=slug, dues='success', _external=True),
            cancel_url=url_for('clubs.home', slug=slug, dues='cancel', _external=True),
        )
    except StripeConnectError as exc:
        current_app.logger.warning('Stripe checkout failed for club %s/user %s: %s', club.id, current_user.id, exc)
        db.session.rollback()
        flash('Stripe checkout is temporarily unavailable. Please contact the club admin.', 'danger')
        return redirect(url_for('clubs.home', slug=slug))

    payment.provider_session_id = checkout['id']
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash('A checkout session already exists. Please try again.', 'warning')
        return redirect(url_for('clubs.home', slug=slug))
    return redirect(checkout['url'])


@stripe_connect_bp.route('/webhook', methods=['POST'])
@csrf.exempt
def webhook():
    secret = current_app.config.get('STRIPE_WEBHOOK_SECRET')
    if not secret:
        abort(404)
    try:
        event = verify_webhook_payload(request.get_data(), request.headers.get('Stripe-Signature'), secret)
    except (StripeConnectError, ValueError) as exc:
        current_app.logger.warning('Rejected Stripe webhook: %s', exc)
        return {'error': 'invalid signature'}, 400

    if event.get('type') != 'checkout.session.completed':
        return {'status': 'ignored'}

    checkout = event.get('data', {}).get('object', {})
    session_id = checkout.get('id')
    if not session_id:
        return {'status': 'missing session id'}, 400

    payment = ClubMembershipPayment.query.filter_by(provider_session_id=session_id).first()
    if not payment:
        current_app.logger.warning('Stripe webhook had unknown checkout session %s', session_id)
        return {'status': 'unknown session'}, 200
    if payment.status == 'paid':
        return {'status': 'already processed'}

    payment.status = 'paid'
    payment.provider_payment_intent_id = checkout.get('payment_intent')
    payment.paid_at = datetime.now(timezone.utc)
    activate_membership_dues(payment.membership, paid_at=payment.paid_at)
    db.session.commit()
    return {'status': 'processed'}
