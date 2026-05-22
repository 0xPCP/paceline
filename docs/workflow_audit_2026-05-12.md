# Paceline Workflow Audit - 2026-05-12

This document maps the workflows that should work on Paceline and records the live browser audit results. The live audit uses throwaway users and clubs only. Do not alter `phil@pcp.dev` or the `Paceline Demo Club`.

## Workflow Inventory

### Visitor and Authentication

| Workflow | Expected path | Important permutations |
|---|---|---|
| Beta gate | Visitor opens site, enters beta password, reaches requested page | Invalid beta password, deep link preserves destination |
| Registration | Visitor opens Register, enters username/email/password, account is created, user can sign in | Duplicate email, duplicate username, password validation, username finalized |
| Login | Existing user signs in with email/password | Invalid password, inactive account, MFA-enabled account, trust-browser option |
| Google OAuth | User signs in or registers with Google | Existing email links to account, new Google user must set username |
| Password reset | User requests reset, receives email, follows token, sets new password | Token reuse blocked, expired token blocked, Google-created user can set password |
| MFA | User enables MFA, receives backup codes, MFA required on password login | Bad TOTP, backup code single use, disable MFA |
| Logout | User logs out and protected pages require login again | Session revocation, stale non-trusted session after six hours |

### Rider Workflows

| Workflow | Expected path | Important permutations |
|---|---|---|
| Profile management | User edits profile, zip, bio, emergency contact, language, Strava URL, notification preferences | Invalid Strava profile URL, profile save preserving notification settings |
| Club discovery | User browses Find Clubs, Discover Rides, and Map | Search, zip/radius filtering, hidden clubs excluded, private clubs discoverable but protected |
| Join auto-approval club | User joins, membership becomes active immediately | Full club hosting vs rides-only club |
| Join manual-approval club | User joins, membership is pending until admin approves or rejects | Signup blocked while pending |
| Paid dues club | User joins, sees dues-required state, completes Stripe Checkout | Stripe connected, Stripe onboarding incomplete, Stripe unavailable |
| Waiver | User signs annual waiver before joining restricted rides | Updated waiver requires re-signing |
| Club ride signup | Active member opens ride, signs up, can cancel signup | Waitlist when full, anonymous signup, blocked if membership/waiver/dues missing |
| Ride comments | Signed-in rider comments on ride and can delete own comment | Club admin can delete any comment |
| Garmin GroupRide code | Signed-up rider can add code if blank, leader/admin can edit/clear | Non-signed-up rider blocked, existing code protected |
| Media | Rider uploads post-ride photos/videos | Before ride date blocked, non-image blocked, private club media protected |
| Club board | Member views board, posts text/photo, replies, reacts, subscribes | Non-member blocked, admin pin/delete, digest notifications |
| Personal rides | User creates, edits, deletes public/private personal rides | Weekly quota, invite/access flow for private rides, other user signup |

### Club Owner and Manager Workflows

| Workflow | Expected path | Important permutations |
|---|---|---|
| Create club | User creates club, becomes owner/admin/member, club starts hidden | Full Club vs Rides Only, public/private setup |
| Club settings | Admin edits club profile, visibility, membership rules, hosting mode, weather thresholds, dues, embed | Hidden/public toggle, private toggle, rides-only disables membership features |
| Team roles | Admin adds/removes managers and roles | Admin, ride manager, content editor, treasurer permission boundaries |
| Membership management | Admin adds members, approves/rejects pending, confirms dues, removes members | Manual dues expiration dates, paid-through imports |
| Invites and imports | Admin invites one user or bulk imports roster | New user setup token, existing user claim invite, duplicates, row-level paid-through date |
| Ride management | Admin creates, edits, cancels, deletes rides and recurring rides | New ride email, cancellation email, weather auto-cancel, roster/attendance |
| Ownership transfer | Owner transfers club to another user, recipient confirms by email | Superadmin manual owner change |
| News posts | Content manager creates/edits/deletes club news | Instant club news email, XSS-safe rendering |
| Leaders and sponsors | Admin manages public leader and sponsor rosters | Logo uploads, ordering |
| Embed widget | Admin copies iframe and external site shows upcoming rides | Full-page iframe, narrow iframe, no main nav, hidden clubs 404 |
| Stripe Connect dues | Admin starts/returns from Stripe onboarding and accepts connected dues | Connect incomplete, webhook payment activation |

### Superadmin Workflows

| Workflow | Expected path | Important permutations |
|---|---|---|
| Dashboard | Superadmin sees site stats, growth, storage, email metrics, warnings | Email cap update, storage warning thresholds, slow dashboard warning |
| User management | Search/filter users, view detail, reset password, toggle active/admin, revoke sessions | Cannot alter own admin/active/session status, bootstrap superadmin protected |
| Club superadmin | View club facts, toggle private/verified, transfer owner, delete club with typed confirmation | Delete confirmation required, never delete Paceline Demo Club |
| User-hosted rides | Superadmin lists user-hosted rides and filters private rides | Regular users blocked |
| Feedback | Superadmin views feedback, marks read | Email notification sent on new feedback |
| Geocoding | Superadmin bulk geocodes missing club coordinates | Lookup failure handled |
| Error log | Superadmin views recent errors and details | Regular users blocked |

## Live Browser Audit Plan

The live Playwright audit should cover at least:

1. Register two throwaway users.
2. Log in as the owner user and update profile/notification preferences.
3. Create a throwaway hidden club, then configure it enough for testing.
4. Create a ride as the club owner.
5. Make the club public for the test window and verify the second user can discover/join/signup.
6. Exercise board subscribe/post/reply where available.
7. Create a personal ride and verify another user can sign up.
8. Log in as superadmin and verify dashboard, user list search, club superadmin page, user-hosted rides list, feedback page, and email cap control.
9. Clean up by deleting the throwaway club through the superadmin-confirmed club delete workflow and deactivating throwaway users if user deletion is not available.

## Live Audit Results

Automated headless Chrome audit completed against `https://paceline-2akis.ondigitalocean.app` on May 12, 2026 at 8:37 PM EDT. Full machine-readable output is in `tests/live-workflow-audit/20260513003716/results.json`; the human summary is in `tests/live-workflow-audit/20260513003716/summary.md`.

| Workflow | Status | Notes |
|---|---:|---|
| Visitor beta gate | PASS | Home page loaded after beta gate. |
| Direct registration creates owner account | PASS | Throwaway owner account registered. |
| Owner login | PASS | Fresh browser context could sign in with direct credentials. |
| Owner profile renders | PASS | Profile page loaded after authentication. |
| Owner creates club | PASS | Throwaway club created and owner landed on club admin dashboard. |
| Club settings can publish generated club | PASS | Hidden new club could be made public through settings. |
| Club admin creates ride | PASS | Club admin ride form created a public ride visible in admin rides list. |
| Direct registration creates rider account | PASS | Throwaway rider account registered. |
| Rider login | PASS | Fresh browser context could sign in with direct credentials. |
| Rider joins club and signs up for club ride | PASS | Rider joined the throwaway public club and signed up for its ride. |
| Owner creates personal ride | PASS | Owner created a public user-hosted ride. |
| Rider signs up for personal ride | PASS | Rider signed up for the generated user-hosted ride. |
| Superadmin dashboard and oversight pages | PASS | Dashboard, users, user-hosted rides, feedback, error log, and club superadmin pages rendered. |
| Owner cleanup deletes generated personal ride | PASS | Generated personal ride was deleted through the owner UI before deactivating users. |
| Cleanup generated records | PASS | Generated club was deleted through superadmin typed confirmation. Throwaway users were deactivated because the product does not expose user deletion. |

### Discrepancies Found

No blocking discrepancies were found in the automated core workflow pass.

The first draft of the audit automation created one temporary personal ride before cleanup logic was added. That artifact was cleaned up separately by reactivating `audit_owner_20260513003258@example.com`, deleting `Audit Personal Ride 20260513003258`, and deactivating the user again. The protected `phil@pcp.dev` account and `Paceline Demo Club` were not modified.

### Coverage Gaps for Follow-Up

These workflows are documented above but were not exercised in this automated live pass because they require external services, email inbox access, uploaded media, or deliberate destructive/moderation actions:

- Google OAuth registration/login.
- Password reset and setup-account email token flows.
- MFA setup, challenge, backup-code, and disable flows.
- Stripe Connect onboarding, Stripe dues checkout, and webhook membership activation.
- Bulk member import with paid-through dates.
- Image/media upload flows and storage accounting.
- Club board post/reply/reaction/notification digest behavior.
- Ownership transfer email confirmation.
- Superadmin password reset and session revocation actions.
