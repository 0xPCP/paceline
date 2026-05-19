# Public Beta Launch Readiness

Use this as the final owner-facing checklist before opening Paceline beyond the
current beta audience. The app-side work is largely automated or documented; the
remaining highest-risk items are external-account setup and real-world payment,
email, and device validation.

## App-Side Items Covered

- Production config guard rejects the development `SECRET_KEY` when secure
  cookies are enabled.
- Session cookies default to `Secure`, `HttpOnly`, and `SameSite=Lax`.
- Password sign-ins require re-authentication after 6 hours unless the user
  chooses **Trust this browser**.
- Google OAuth state is validated and first-time Google users must choose a
  unique Paceline username before the account is complete.
- Password setup/reset links are email-verified and password changes revoke
  existing sessions.
- MFA backup codes are single-use and session revocation is tested.
- Stripe Connect dues use direct charges on the connected club account with a
  `$1` Paceline application fee.
- Stripe webhooks require a valid signature; duplicate checkout webhooks are
  idempotent.
- Club dues activation happens from signed webhook events, not browser redirects.
- XSS regression coverage exists for board posts, replies, ride comments,
  platform news, feedback, and Markdown-rendered content.
- Help documentation covers rider security, notifications, dues, Stripe Connect,
  club management, embeds, advanced ride options, and ownership transfer.
- The beta gate no longer redirects to external `next` URLs after successful
  password entry.

## Owner Tasks Before Public Launch

### Google OAuth

- Verify `paceline.club` in Google Cloud Console.
- Set the OAuth consent screen to production when approved.
- Add the production redirect URI:
  `https://paceline.club/auth/google/callback`.
- Confirm the consent screen shows Paceline branding, support email, privacy
  policy URL, and data-use/terms links.
- Complete a real Google registration and first-username setup on production.

### Stripe Live Mode

- Rotate any live Stripe keys that were pasted into chat, logs, or local files
  before accepting real payments.
- Put live Stripe values in DigitalOcean App Platform:
  `STRIPE_SECRET_KEY`, `STRIPE_CONNECT_WEBHOOK_SECRET`, and
  `STRIPE_PLATFORM_FEE_CENTS=100`. `STRIPE_PUBLISHABLE_KEY` is optional for
  future client-side Stripe flows; current club-dues Checkout Sessions are
  created server-side.
- Create `/stripe/webhook` as a **Connect webhook** with **Listen to events on
  connected accounts** enabled.
- Subscribe the Connect webhook to:
  `checkout.session.completed`, `payment_intent.payment_failed`, and
  `charge.failed`.
- Run the live small-dollar validation in `docs/large_test_deployment.md`.
- Confirm Stripe Checkout charges dues plus `$1` total, Stripe shows Paceline's
  `$1` application fee, and the club receives the configured dues amount before
  Stripe processing fees.

### Email

- Confirm Resend domain verification for `paceline.club`.
- Confirm SPF, DKIM, and DMARC are passing.
- Send and inspect real emails for password reset, club invite, ownership
  transfer, feedback notification, cancellation, waitlist promotion, membership
  approval/rejection, and dues reminders.
- Verify Gmail and at least one non-Gmail inbox do not mark Paceline mail as
  spam.

### DigitalOcean and Data Safety

- Confirm Managed PostgreSQL automated backups are enabled.
- Confirm the restore process has been tested or at least rehearsed from the
  documented commands.
- Confirm Spaces credentials are set and private-club media access checks still
  hold in production.
- Confirm DigitalOcean alerts exist for app CPU/memory, PostgreSQL disk, and
  Spaces storage/bandwidth.
- Keep beta/test data cleanup separate from `phil@pcp.dev` and the Paceline Demo
  Club.

### Manual Browser and Device Pass

- Test production on real iPhone Safari.
- Test production on real Android Chrome if available.
- Test desktop Chrome, Safari, and Firefox.
- Confirm Google OAuth, Stripe Checkout handoff, profile-photo upload/crop, map
  controls, and ride signup work on mobile.

## Final Go/No-Go

Do not open paid dues to real clubs until all of these are true:

- Automated suites listed in `docs/large_test_deployment.md` pass.
- Stripe sandbox checkout passes.
- Live small-dollar checkout passes.
- Webhook delivery activates membership.
- A failed or canceled payment does not activate membership.
- Real emails arrive with correct branding and acceptable deliverability.
- Production logs show no recurring 500s during the rehearsal.
- Remaining test clubs/users/media are cleaned up.
