# Superadmin Operations Runbook

This runbook documents Paceline-only administrative workflows that are not part
of the public rider or club-manager help pages.

## Access

Superadmin access is limited to users with `is_admin=true`. The bootstrap
superadmin email should remain configured as:

```text
SUPERADMIN_EMAILS=phil@pcp.dev
```

Do not disable, deactivate, or delete the bootstrap superadmin account. The
application blocks the most dangerous self-actions, but operational discipline
still matters.

## Daily Checks

Review the superadmin dashboard for:

- Site usage statistics and growth charts.
- Email daily/monthly/yearly counts.
- Resend/email delivery failures.
- Stripe Connect checkout and webhook warnings.
- Storage usage and media warnings.
- App error logs and slow dashboard warnings.
- New feedback.
- Recent audit activity.

## Destructive Actions

The following actions should be used deliberately and checked for an audit log
entry after completion:

- Toggle a club private/public.
- Toggle a club verified/unverified.
- Manually transfer club ownership.
- Delete a club after typed confirmation.
- Delete generated test users.
- Revoke a user's sessions.
- Deactivate or reactivate a user.
- Grant or revoke superadmin status.
- Edit a user's dues status.

Club deletion requires typed confirmation. Test-user deletion is intentionally
restricted to generated audit-style accounts and must not be used for real users.

## Ownership Transfer

Use normal owner-initiated transfer whenever possible:

1. Current owner starts transfer from club team/admin tools.
2. Proposed owner receives an email.
3. Proposed owner accepts the transfer while signed in as themselves.

Use superadmin manual transfer only when the current owner is unavailable or the
club has a verified administrative need. Confirm the target email twice before
submitting. The new owner is made an active member and full club admin.

## Production Configuration Checks

Before public beta or live Stripe payments, confirm:

- `COOKIE_SECURE=true`.
- `SECRET_KEY` is a strong production value and not the development default.
- `SUPERADMIN_EMAILS=phil@pcp.dev`.
- `STRIPE_SECRET_KEY` mode matches the environment being tested.
- `STRIPE_CONNECT_WEBHOOK_SECRET` is the Connect webhook signing secret.
- Stripe webhook listens to connected-account events.
- `STRIPE_PLATFORM_FEE_CENTS=100`.
- Email provider domain authentication is healthy.
- Spaces/media configuration points to durable object storage.

## Incident Response

For suspicious account activity:

1. Revoke the user's sessions.
2. Deactivate the account if needed.
3. Review recent audit entries, app error logs, and email activity.
4. Check related club memberships, admin roles, ownership transfers, and recent
   destructive actions.
5. Re-enable only after the owner has reset their password and MFA state is
   understood.

For Stripe issues:

1. Check the superadmin Stripe warning panel.
2. Check Stripe webhook delivery attempts.
3. Confirm the event was sent to the Connect webhook endpoint.
4. Confirm the checkout session exists on the connected account.
5. Do not manually activate membership until the payment is verified in Stripe.

