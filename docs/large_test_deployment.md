# Large Test Deployment Runbook

This runbook defines the full Paceline test deployment to run before switching
Stripe dues from sandbox/test mode to live payments and before opening the beta
more broadly.

The goal is to prove the complete product works as a connected system: auth,
club creation, ride management, paid dues, Stripe Connect, email, media,
superadmin oversight, cleanup, and public documentation.

## Scope

This test deployment is larger than a smoke test. It should exercise the same
paths a real club and real rider will use during public beta.

Do not modify or delete:

- `phil@pcp.dev`
- `Paceline Demo Club`
- production Stripe live connected accounts, unless explicitly running the live
  penny/small-dollar validation described below

Generated test users should use obvious prefixes:

- `e2e_checkout_*`
- `audit_owner_*`
- `audit_rider_*`
- `launch_owner_*`
- `launch_rider_*`

Generated test clubs should use obvious names/slugs:

- `launch-test-*`
- `audit-workflow-club-*`

## Test Environments

### Sandbox test deployment

Use this for normal rehearsal:

- App: DigitalOcean deployment URL, usually
  `https://paceline-2akis.ondigitalocean.app`
- Beta password: configured separately in the environment
- Stripe: test mode keys
- Webhook: Stripe Connect test webhook endpoint
- Test cards: Stripe test cards

### Live preflight deployment

Use this only after the sandbox run passes:

- App: `https://paceline.club`
- Stripe: live keys
- Webhook: Stripe Connect live webhook endpoint
- Payment: one real small-dollar dues checkout on a temporary non-demo club

## Required Stripe Configuration

Paceline uses Stripe Connect direct charges for automated club dues.

Required environment variables:

```text
STRIPE_SECRET_KEY=sk_test_... or sk_live_...
STRIPE_CONNECT_WEBHOOK_SECRET=whsec_...
STRIPE_PLATFORM_FEE_CENTS=100
```

`STRIPE_WEBHOOK_SECRET` is optional fallback/platform webhook configuration. For
direct-charge dues, the important secret is `STRIPE_CONNECT_WEBHOOK_SECRET`.

In Stripe Dashboard, create the webhook endpoint as a **Connect webhook**:

1. Go to Developers -> Webhooks.
2. Add endpoint: `https://paceline.club/stripe/webhook` for live, or the
   DigitalOcean direct URL for sandbox testing.
3. Enable **Listen to events on connected accounts**.
4. Subscribe at minimum to:
   - `checkout.session.completed`
   - `payment_intent.payment_failed`
   - `charge.failed`
5. Copy the Connect endpoint signing secret to `STRIPE_CONNECT_WEBHOOK_SECRET`.

For direct charges, Checkout Sessions are created on the club's connected
account using the `Stripe-Account` header. Paceline collects its fee using
`payment_intent_data[application_fee_amount]=100`. Do not use
`transfer_data[destination]` for this flow.

## Existing Automated Coverage

Use these existing suites as the base of the large test deployment:

```bash
.venv/bin/python -m pytest tests/test_auth.py tests/test_google_mfa.py tests/test_password_reset.py -q
.venv/bin/python -m pytest tests/test_membership.py tests/test_stripe_connect_dues.py tests/test_club_import.py -q
.venv/bin/python -m pytest tests/test_workflow_new_user.py tests/test_workflow_club_creator.py -q
.venv/bin/python -m pytest tests/test_superadmin.py tests/test_feedback.py tests/test_notifications.py tests/test_email.py -q
.venv/bin/python -m pytest tests/test_security.py tests/test_privacy.py tests/test_donate.py tests/test_help.py -q
.venv/bin/python -m pytest tests/test_storage.py tests/test_media.py tests/test_board.py -q
.venv/bin/python -m pytest tests/test_embed.py tests/test_map.py tests/test_discovery.py tests/test_dashboard.py -q
```

Browser/UI coverage:

```bash
.venv/bin/python -m pytest tests/test_browser_mobile.py tests/test_browser_prod_audit.py -q
.venv/bin/python -m pytest tests/test_browser_workflow_new_user.py tests/test_browser_workflow_club_creator.py -q
```

Stripe browser E2E coverage:

```bash
.venv/bin/python -m pytest tests/test_e2e_stripe_checkout.py -v -s
```

The Stripe E2E test currently expects a test club with Stripe Connect dues
enabled and a connected test Stripe account. It covers successful checkout,
cancel/abandon flow, and declined-card behavior.

## Manual-Only Coverage

These items are not fully covered by the automated suite and must be checked
manually during the launch rehearsal.

### Stripe Dashboard and Account Setup

- Confirm Paceline's Stripe account is fully activated for live charges.
- Confirm Paceline branding, support email, statement descriptor, and public
  business profile are correct in Stripe.
- Confirm Connect is enabled and the platform profile is complete.
- Confirm the webhook endpoint is a **Connect webhook**, not only a normal
  platform webhook.
- Confirm **Listen to events on connected accounts** is enabled.
- Confirm the live webhook secret in DigitalOcean matches the Connect webhook
  endpoint, not the platform webhook endpoint.
- Confirm live/test mode keys are not mixed.
- Confirm any Stripe secret keys previously pasted into chat/logs have been
  rotated before live payments.
- Confirm the Stripe Dashboard shows Paceline's `$1` application fee on a test
  connected-account payment.

### Connected Club Account Reality

- Complete Stripe-hosted onboarding as a real club admin.
- Leave onboarding incomplete and confirm the club cannot enable automated dues.
- Finish onboarding and confirm the club can accept charges.
- Confirm the connected club account can see its own charge/refund/dispute
  records in Stripe.
- Confirm club payout status and bank setup look correct in Stripe.

### Real Live Payment Settlement

- Run one live small-dollar dues payment on a temporary non-demo club.
- Confirm the rider's membership activates only after webhook delivery.
- Confirm the connected club account receives the dues.
- Confirm Paceline receives the `$1` application fee.
- Confirm the Stripe receipt/checkout copy looks acceptable to a real rider.
- Confirm a real refund path from the club account behaves as expected.
- Confirm Paceline's `$1` fee policy is followed.

### Email Inbox and Deliverability

- Verify real password reset email arrives in an external inbox.
- Verify imported-member setup email arrives in an external inbox.
- Verify club ownership transfer email arrives and the link works.
- Verify membership approval/rejection/dues emails render correctly in a real
  inbox.
- Verify Stripe failure alert reaches the superadmin inbox.
- Verify SPF/DKIM/DMARC status in Resend or the email provider dashboard.
- Verify emails do not land in spam for at least Gmail and one non-Gmail inbox.

### Google OAuth and MFA

- Complete Google OAuth registration with a real Google account.
- Confirm first Google login requires a unique Paceline username.
- Confirm existing email account linking works as intended.
- Confirm Google-created users can set a Paceline password by email verification.
- Scan MFA QR code with a real authenticator app.
- Confirm backup codes are saved and one backup code works exactly once.

### Browser and Device UX

- Test on a real iPhone Safari browser.
- Test on a real Android Chrome browser if available.
- Test desktop Chrome, Safari, and Firefox.
- Confirm Stripe Checkout handoff and return works on mobile.
- Confirm image upload/crop works from a mobile photo library.
- Confirm map controls and geolocation prompts are usable on mobile.
- Confirm club embed code renders correctly when pasted into a simple external
  HTML page.

### Legal, Policy, and Trust Copy

- Read privacy policy and data-use policy as a new user would.
- Confirm onboarding requires policy acknowledgement.
- Confirm donation language accurately states Stripe collects payment/contact
  information.
- Confirm paid-dues copy says Paceline collects a `$1` platform fee.
- Confirm docs say clubs handle refunds and disputes.
- Confirm there is a clear way for users and club admins to contact Paceline.

### Operational Checks

- Review DigitalOcean deployment logs after the test run.
- Review app error logs in the superadmin panel.
- Review Resend/email provider logs.
- Review Stripe webhook delivery attempts and failures.
- Review Stripe payment events and connected-account events.
- Confirm DigitalOcean backups are enabled for PostgreSQL.
- Confirm rollback procedure is understood before enabling live payments.

## Large Test Case

Run this as one coordinated launch rehearsal.

### Phase 1: Environment Verification

Verify:

- App deploy is active.
- Version footer matches the commit being tested.
- Database migrations are current.
- `COOKIE_SECURE=true` in deployed environments.
- `SUPERADMIN_EMAILS=phil@pcp.dev`.
- Email provider is configured.
- Stripe test keys are configured.
- `STRIPE_CONNECT_WEBHOOK_SECRET` is configured.
- `STRIPE_PLATFORM_FEE_CENTS=100`.
- Spaces/media storage config is correct for the environment.

Pass criteria:

- App loads.
- Superadmin dashboard loads.
- No startup errors in DigitalOcean logs.
- `/stripe/webhook` rejects bad signatures with `400`, not `500`.

### Phase 2: Visitor and Account Workflows

Test:

- Beta gate accepts valid password.
- Beta gate preserves deep links.
- Direct registration works.
- Duplicate email is rejected.
- Duplicate username is rejected.
- Login works.
- Logout works.
- Six-hour non-trusted session behavior still requires re-auth.
- Trusted-browser login remains trusted.
- Password reset sends email and token works.
- Expired/reused password reset token fails safely.
- Google OAuth login works.
- Google OAuth first sign-in prompts for unique username.
- MFA setup works for password users.
- MFA challenge rejects bad code.
- Backup code works once.

Pass criteria:

- No user can bypass account completion.
- No duplicate username is created.
- Failed auth paths show clear user-facing messages.

### Phase 3: Club Owner Full-Club Workflow

Create a temporary full-hosting club.

Test:

- Club starts hidden.
- Owner is set.
- Owner is admin and active member.
- Settings can be saved.
- Club can be made public.
- Club can be made private and returned public.
- Club can be switched between full-hosting and rides-only without losing rides.
- Admin team roles work:
  - admin
  - ride manager
  - content editor
  - treasurer
- Ownership transfer email is sent.
- Pending ownership transfer can be accepted.
- Superadmin can manually transfer ownership.

Pass criteria:

- Permission boundaries hold.
- Non-admin users cannot access admin pages.
- Hidden clubs do not appear in public listing/map/search.

### Phase 4: Club Membership and Dues

For the same temporary club, enable membership and paid dues.

Test manual dues:

- Rider joins paid club.
- Rider becomes `pending_payment`.
- Club admin can manually confirm paid dues.
- Paid-through date is set.
- Member appears active.
- Member can sign up for rides.
- CSV export includes dues status.
- Member roster filters active/pending/payment/expired correctly.

Test Stripe Connect dues in test mode:

- Club admin starts Stripe-hosted onboarding.
- Incomplete onboarding returns with clear warning.
- Completed onboarding marks the account connected.
- Club settings show connected status.
- Rider joins paid club.
- Rider sees Pay Club Dues.
- Checkout creates direct charge on the connected account.
- Checkout includes `Stripe-Account: acct_...`.
- Checkout includes `application_fee_amount=100`.
- Checkout does not include `transfer_data[destination]`.
- Rider sees only the club dues line item.
- Successful payment activates membership from signed webhook.
- Duplicate webhook does not extend membership twice.
- Unknown checkout session returns `200` to prevent Stripe retry loops.
- Declined card does not activate membership.
- Canceled checkout leaves membership `pending_payment`.
- Payment failure logs an error and sends superadmin alert.

Renewal tests:

- Active member more than 30 days from expiration cannot renew early.
- Active member within 30 days can renew.
- Renewal stacks from existing expiration date.
- Expired member renewal starts from today.
- Dues reminder state resets after successful payment.

Pass criteria:

- Membership activation only happens from webhook, never from browser redirect.
- Paceline fee remains exactly `$1`.
- Club dues remain associated with the club's connected Stripe account.

### Phase 5: Ride Management

Create several rides:

- Public club ride
- Private/member-only club ride
- Recurring ride
- Ride with capacity/waitlist
- Ride requiring waiver
- Ride requiring paid dues
- User-hosted public ride
- User-hosted private ride
- Virtual ride

Test:

- Ride manager can create/edit/cancel rides.
- Non-manager cannot.
- Rider can sign up for eligible ride.
- Rider cannot sign up when membership, waiver, or dues are missing.
- Waitlist behavior works.
- Cancellation email is queued/sent.
- Attendance can be recorded.
- Garmin GroupRide field permissions hold.
- Weather/AQI display renders.
- Weather warning thresholds err toward continuing rides unless truly bad.

Pass criteria:

- No protected route/location details leak for private clubs.
- Ride signup buttons are clear and consistent.
- Canceled rides are visually obvious.

### Phase 6: Boards, Posts, Notifications, and Email

Test:

- Club news post creates instant club email.
- Board post/reply/reaction works for active members.
- Board digest queues instead of sending one email per event.
- Mentions queue digest items.
- User notification preferences are respected.
- Required transactional emails bypass optional caps.
- Superadmin daily email cap can be edited.
- Daily/monthly/yearly email counts update.
- Resend failure behavior logs and retries appropriately.

Pass criteria:

- No notification path can spam a user past the configured cap except required transactional mail.
- Email branding is consistent.

### Phase 7: Media, Profiles, Leaders, and Privacy

Test:

- Profile photo upload works.
- Profile photo crop/pan UI works.
- Public/private profile settings work.
- Public profile links render correctly.
- Friend/follow ride settings work.
- Ride leader roster can use member profile photos.
- Sponsor logos upload and display.
- Ride media uploads after ride date.
- Non-image upload rejected.
- Private club media requires authorization.
- Public media redirects to CDN/public URL when configured.
- Storage usage appears in superadmin dashboard.

Pass criteria:

- Private content does not leak through media URLs.
- Upload failures are handled without breaking the page.

### Phase 8: Discovery, Map, Embeds, and Mobile UI

Test:

- Find Clubs search.
- Discover Rides filters.
- Map controls are visible before hover.
- Hidden clubs excluded.
- Featured clubs display correctly.
- Embed widget scales from mobile width to full-page iframe.
- Header/footer consistent across pages.
- Mobile layouts for homepage, club, ride, map, profile, and checkout entry.

Pass criteria:

- No unreadable controls.
- No overlapping UI.
- Embeds do not show full site chrome.

### Phase 9: Superadmin Oversight

Test:

- Dashboard stats render.
- Growth charts render.
- Storage warnings render.
- Email monitoring renders.
- Stripe monitoring renders.
- App error log renders.
- User search/filter works.
- User detail page can reset password and edit dues.
- Protected superadmin bootstrap account cannot be disabled accidentally.
- Club private/public toggle works.
- Club delete requires typed confirmation.
- Test-user delete only works for obvious generated users.
- Feedback can be marked read.

Pass criteria:

- Normal users get `403`/redirect from all superadmin routes.
- Destructive actions require confirmation and are logged where applicable.

### Phase 10: Security Regression

Run:

```bash
.venv/bin/python -m pytest tests/test_security.py tests/test_privacy.py tests/test_auth.py -q
.venv/bin/python -m pytest tests/test_security_audit.py -q
```

Manually verify:

- Club status/news/body content is escaped or sanitized.
- Malicious links do not execute JavaScript.
- Uploaded images cannot be served as executable content.
- CSRF protection works on state-changing forms.
- Session cookies are secure/HTTP-only/SameSite.
- Stripe webhook bad signature returns `400`.
- Unauthorized club admin/superadmin routes are blocked.

Pass criteria:

- No XSS path survives in club posts, ride comments, board posts, or profile fields.
- Session theft risk controls remain intact.
- Superadmin destructive actions create audit records.
- Production-like config rejects development secrets when secure cookies are enabled.

### Phase 11: Performance and Capacity

Run focused local performance regression:

```bash
.venv/bin/python -m pytest tests/test_perf.py -q
```

Optional Locust rehearsal:

```bash
.venv/bin/locust -f tests/locustfile.py --headless --users 1000 --spawn-rate 50 --run-time 3m
```

Use `docs/capacity_planning.md` to interpret results.

Pass criteria:

- No 500s.
- p95 remains acceptable for expected beta traffic.
- No database pool exhaustion.

### Phase 12: Cleanup

Clean up:

- Generated clubs.
- Generated personal rides.
- Generated test users via superadmin "Delete test user" where eligible.
- Stripe test customers/sessions if desired.
- Uploaded test media if not cleaned by app workflows.

Verify after cleanup:

- `phil@pcp.dev` unchanged.
- `Paceline Demo Club` unchanged.
- No launch test clubs are public.
- No test users remain active unless intentionally preserved.

## Live Small-Dollar Validation

Run this only after sandbox passes.

1. Create a temporary non-demo club.
2. Connect a real Stripe connected account controlled by the tester.
3. Set dues to the smallest practical live test amount.
4. Join as a temporary rider.
5. Pay dues with a real payment method.
6. Confirm:
   - membership activates from webhook
   - club Stripe account sees the charge
   - Paceline receives the `$1` application fee
   - dashboard logs/counts update
7. If refunding the club dues, verify the policy:
   - club handles refund/dispute
   - Paceline `$1` fee is not refunded
   - membership is either left alone or flagged for admin review according to the current implementation

Do not open this flow to real clubs until the live small-dollar validation
passes.

## Exit Criteria

The test deployment is ready for public beta when:

- All required automated suites pass.
- Stripe sandbox direct-charge checkout passes.
- Connect webhook events activate memberships.
- Failed/canceled/declined payments behave correctly.
- Live small-dollar validation passes.
- Superadmin dashboard shows useful Stripe/email/storage/error state.
- Generated test data is cleaned up.
- DigitalOcean logs show no new recurring 500s.
- Public help/privacy/data-use pages match the implemented behavior.

## Documentation Follow-Up

After this test deployment passes, rewrite the club documentation around the
tested behavior, not the planned behavior. The club docs should include:

- Full club vs rides-only setup.
- Manual dues vs Stripe Connect dues.
- Stripe-hosted onboarding screenshots.
- Direct-charge explanation in plain language.
- `$1 Paceline platform fee` disclosure.
- Refund/dispute responsibility.
- Member roster and dues management screenshots.
- Ride creation, embeds, leaders, sponsors, and notification guidance.
