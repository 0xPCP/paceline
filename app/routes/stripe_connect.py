from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, abort, current_app, flash, redirect, request, url_for
from flask_login import current_user, fresh_login_required, login_required
from sqlalchemy.exc import IntegrityError

from ..extensions import csrf, db
from ..membership_dues import activate_membership_dues
from ..models import Club, ClubMembership, ClubMembershipPayment, ClubShopItem, ClubShopOrder
from ..stripe_connect import (
    StripeConnectError,
    connect_enabled,
    create_connected_account,
    create_checkout_session,
    create_shop_checkout_session,
    create_onboarding_link,
    retrieve_connected_account,
    verify_webhook_payload,
)

stripe_connect_bp = Blueprint('stripe_connect', __name__)


def _visible_club_or_404(slug):
    return Club.query.filter_by(slug=slug, is_active=True, is_hidden=False).first_or_404()


def _admin_club_or_404(slug):
    return Club.query.filter_by(slug=slug, is_active=True).first_or_404()


@stripe_connect_bp.route('/clubs/<slug>/connect')
@fresh_login_required
def connect_club(slug):
    club = _admin_club_or_404(slug)
    if not current_user.is_club_admin(club):
        abort(403)
    if not connect_enabled():
        flash('Stripe Connect is not configured for this Paceline environment yet.', 'warning')
        return redirect(url_for('admin.club_settings', slug=slug))

    try:
        if not club.stripe_account_id:
            account = create_connected_account(club=club, user=current_user)
            club.stripe_account_id = account['id']
            db.session.commit()

        link = create_onboarding_link(
            account_id=club.stripe_account_id,
            refresh_url=url_for('stripe_connect.connect_club', slug=club.slug, _external=True),
            return_url=url_for('stripe_connect.onboarding_return', slug=club.slug, _external=True),
        )
    except StripeConnectError as exc:
        current_app.logger.warning('Stripe Connect onboarding failed for club %s: %s', club.id, exc)
        db.session.rollback()
        flash('Stripe could not start onboarding for this club. Please try again.', 'danger')
        return redirect(url_for('admin.club_settings', slug=slug))

    return redirect(link['url'])


@stripe_connect_bp.route('/connect/callback')
@login_required
def oauth_callback():
    flash('Stripe Connect now uses hosted onboarding. Please start again from club settings.', 'info')
    return redirect(url_for('clubs.index'))


@stripe_connect_bp.route('/clubs/<slug>/connect/return')
@login_required
def onboarding_return(slug):
    club = _admin_club_or_404(slug)
    if not current_user.is_club_admin(club):
        abort(403)
    if not club.stripe_account_id:
        flash('Stripe did not return a connected account. Please try again.', 'warning')
        return redirect(url_for('admin.club_settings', slug=club.slug))

    try:
        account = retrieve_connected_account(club.stripe_account_id)
    except StripeConnectError as exc:
        current_app.logger.warning('Stripe Connect account status check failed for club %s: %s', club.id, exc)
        flash('Stripe onboarding started. Refresh this page after Stripe finishes verification.', 'info')
        return redirect(url_for('admin.club_settings', slug=club.slug))

    if account.get('charges_enabled'):
        club.stripe_account_connected_at = datetime.now(timezone.utc)
        flash('Stripe Connect onboarding is linked for paid dues and shop checkout.', 'success')
    else:
        flash('Stripe onboarding was saved. Finish Stripe verification before using paid dues or shop checkout.', 'info')
    db.session.commit()
    return redirect(url_for('admin.club_settings', slug=club.slug))


@stripe_connect_bp.route('/clubs/<slug>/disconnect', methods=['POST'])
@fresh_login_required
def disconnect_club(slug):
    club = _admin_club_or_404(slug)
    if not current_user.is_club_admin(club):
        abort(403)
    club.stripe_account_id = None
    club.stripe_account_connected_at = None
    club.membership_dues_required = False
    if club.membership_dues_mode == 'stripe_connect':
        club.membership_dues_mode = 'manual'
    db.session.commit()
    flash('Stripe Connect was disconnected. Paid dues and shop checkout are now disabled for this club.', 'info')
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
        expiring_soon = (
            membership.dues_paid_until is not None
            and membership.dues_paid_until <= date.today() + timedelta(days=30)
        )
        if not expiring_soon:
            flash('Your membership is already active.', 'info')
            return redirect(url_for('clubs.home', slug=slug))
    if membership is None:
        membership = ClubMembership(user_id=current_user.id, club_id=club.id, status='pending_payment')
        db.session.add(membership)
        db.session.flush()
    else:
        membership.status = 'pending_payment'

    platform_fee_cents = current_app.config.get('STRIPE_PLATFORM_FEE_CENTS', 100)
    payment = ClubMembershipPayment(
        club_id=club.id,
        user_id=current_user.id,
        membership_id=membership.id,
        amount_cents=club.membership_dues_amount_cents + platform_fee_cents,
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


@stripe_connect_bp.route('/clubs/<slug>/shop/<int:item_id>/checkout', methods=['POST'])
@login_required
def shop_checkout(slug, item_id):
    club = _visible_club_or_404(slug)
    if not club.stripe_connect_ready:
        flash('Online shop checkout is not available for this club yet.', 'warning')
        return redirect(url_for('clubs.club_shop', slug=slug))

    item = ClubShopItem.query.filter_by(
        id=item_id,
        club_id=club.id,
        is_active=True,
    ).first_or_404()

    platform_fee_cents = current_app.config.get('STRIPE_PLATFORM_FEE_CENTS', 100)
    order = ClubShopOrder(
        club_id=club.id,
        item_id=item.id,
        user_id=current_user.id,
        item_amount_cents=item.price_cents,
        platform_fee_cents=platform_fee_cents,
        amount_cents=item.price_cents + platform_fee_cents,
        currency=item.currency or 'usd',
        customer_email=current_user.email,
    )
    db.session.add(order)
    db.session.flush()

    try:
        checkout = create_shop_checkout_session(
            club=club,
            user=current_user,
            item=item,
            order=order,
            success_url=url_for('clubs.club_shop', slug=slug, shop='success', _external=True),
            cancel_url=url_for('clubs.club_shop', slug=slug, shop='cancel', _external=True),
        )
    except StripeConnectError as exc:
        current_app.logger.warning('Stripe shop checkout failed for club %s/item %s/user %s: %s', club.id, item.id, current_user.id, exc)
        db.session.rollback()
        flash('Stripe checkout is temporarily unavailable. Please contact the club admin.', 'danger')
        return redirect(url_for('clubs.club_shop', slug=slug))

    order.provider_session_id = checkout['id']
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash('A checkout session already exists. Please try again.', 'warning')
        return redirect(url_for('clubs.club_shop', slug=slug))
    return redirect(checkout['url'])


@stripe_connect_bp.route('/webhook', methods=['POST'])
@csrf.exempt
def webhook():
    # Prefer the Connect webhook secret (events from connected accounts);
    # fall back to the platform account webhook secret if not set.
    secret = (
        current_app.config.get('STRIPE_CONNECT_WEBHOOK_SECRET')
        or current_app.config.get('STRIPE_WEBHOOK_SECRET')
    )
    if not secret:
        abort(404)
    raw = request.get_data()
    try:
        event = verify_webhook_payload(raw, request.headers.get('Stripe-Signature'), secret)
    except (StripeConnectError, ValueError) as exc:
        current_app.logger.warning('Rejected Stripe webhook: %s', exc)
        return {'error': 'invalid signature'}, 400

    event_type = event.get('type', '')
    obj = event.get('data', {}).get('object', {})

    # ── Successful checkout ───────────────────────────────────────────────────
    if event_type == 'checkout.session.completed':
        session_id = obj.get('id')
        if not session_id:
            return {'status': 'missing session id'}, 400

        payment = ClubMembershipPayment.query.filter_by(provider_session_id=session_id).first()
        if payment:
            if payment.status == 'paid':
                return {'status': 'already processed'}

            payment.status = 'paid'
            payment.provider_payment_intent_id = obj.get('payment_intent')
            payment.paid_at = datetime.now(timezone.utc)
            activate_membership_dues(payment.membership, paid_at=payment.paid_at)
            db.session.commit()
            return {'status': 'processed'}

        order = ClubShopOrder.query.filter_by(provider_session_id=session_id).first()
        if order:
            if order.status == 'paid':
                return {'status': 'already processed'}
            order.status = 'paid'
            order.provider_payment_intent_id = obj.get('payment_intent')
            order.amount_cents = obj.get('amount_total') or order.amount_cents
            total_details = obj.get('total_details') or {}
            order.tax_amount_cents = total_details.get('amount_tax') or 0
            shipping_cost = obj.get('shipping_cost') or {}
            order.shipping_amount_cents = shipping_cost.get('amount_total') or 0
            customer_details = obj.get('customer_details') or {}
            order.customer_email = customer_details.get('email') or order.customer_email
            order.customer_name = customer_details.get('name')
            order.shipping_details = obj.get('shipping_details') or customer_details.get('address')
            order.paid_at = datetime.now(timezone.utc)
            db.session.commit()
            return {'status': 'shop order processed'}

        current_app.logger.warning('Stripe webhook had unknown checkout session %s', session_id)
        return {'status': 'unknown session'}, 200

    # ── Payment failure ───────────────────────────────────────────────────────
    if event_type in ('payment_intent.payment_failed', 'charge.failed'):
        pi_id = obj.get('id') if event_type == 'payment_intent.payment_failed' else obj.get('payment_intent')
        error_msg = (
            obj.get('last_payment_error', {}).get('message')
            or obj.get('failure_message')
            or 'Unknown failure'
        )
        current_app.logger.warning('Stripe payment failed: %s %s — %s', event_type, pi_id, error_msg)

        # Find the related payment record (may not exist for retries before session completes)
        payment = None
        if pi_id:
            payment = ClubMembershipPayment.query.filter_by(
                provider_payment_intent_id=pi_id
            ).first()

        # Log to AppErrorLog so it appears in the error dashboard
        from ..models import AppErrorLog
        db.session.add(AppErrorLog(
            status_code=0,
            method='STRIPE',
            path=f'/stripe/webhook ({event_type})',
            error_type='stripe_payment_failed',
            error_message=f'{event_type} | pi={pi_id} | {error_msg}',
        ))
        db.session.commit()

        # Email platform owner
        from ..email import send_stripe_error_alert
        send_stripe_error_alert(
            event_type=event_type,
            payment_intent_id=pi_id,
            error_message=error_msg,
            payment=payment,
        )
        return {'status': 'failure_logged'}

    return {'status': 'ignored'}
