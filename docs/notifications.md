# Paceline Email Notification Strategy

Paceline treats "notifications" as email notifications. The goal is to keep riders informed without creating high email volume or unnecessary Resend cost.

## Notification Categories

### Required Transactional Email

These emails are always sent when applicable and are not user-configurable:

- Password setup and password reset links
- Club invite and imported-account setup links
- Club ownership transfer confirmation
- Site feedback notifications to superadmins
- Security-sensitive account emails

### User-Configurable Ride and Club Email

These are managed from the user's profile:

- Ride cancellations
- Morning ride reminders
- Waitlist promotions
- Major ride changes
- Membership approvals, rejections, and dues updates
- New rides from joined clubs
- Club news posts
- Weekly club digest
- Daily message board digest

Default behavior:

- New club rides are instant by default.
- Club news posts are instant by default.
- Weekly club digests are on by default.
- Ride cancellations, reminders, and waitlist promotions are on by default.
- Membership updates are on by default.
- Message board activity is delivered as a digest instead of instant per-event email.

## Message Board Digest

Board activity is queued into `board_digest_items` and sent by the scheduler as a daily digest.

Digest events include:

- New board posts in clubs where the user subscribed to board notifications
- Replies to the user's board posts
- Mentions of the user with `@username`

The digest job sends at 18:00 server time and marks queued items as sent after the digest is delivered.

## Daily User Email Cap

Superadmins can set the daily per-user notification cap from the Super Admin Dashboard. The default is `15` emails per user per day.

The cap applies to configurable notifications. Required transactional emails are not blocked by this cap.

Per-user cap telemetry is stored in `user_email_logs`:

- `sent` means the user was selected for delivery.
- `capped` means the notification was skipped because the user had already reached the daily cap.

Aggregate provider telemetry remains in `email_delivery_logs` and powers the dashboard's daily, monthly, yearly, and total email counts.

## Implementation Notes

- User preferences are stored as JSON in `users.email_preferences`.
- The superadmin cap is stored in `site_settings.email_daily_cap`.
- Existing email helpers call a preference-aware send path for configurable notifications.
- Required transactional helpers continue to bypass preference filtering where appropriate.
- Tests live in `tests/test_notifications.py`.

## Future Improvements

- Add per-club notification overrides.
- Add account-level unsubscribe links in non-required emails.
- Add `account.updated` handling for Stripe Connect onboarding status.
- Add digest frequency choices: daily, weekly, or off.
- Add ride comment subscription controls.
