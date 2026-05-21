# TODO

## Production Deployment: DigitalOcean

Status: planned.

The long-term production deployment model is documented in
`docs/digitalocean_deployment.md`. Future feature work should be compatible
with that model.

### Before Production Cutover

- Finish Stripe Connect dues with direct charges, Stripe-hosted onboarding,
  a transparent $1 Paceline platform fee, signed webhooks, and club-owned
  refund/dispute handling.
- Add DigitalOcean Spaces support for ride photo uploads.
- Keep local filesystem media storage for tests and local/TrueNAS dev.
- Preserve private-club media access checks when serving media from Spaces.
- Update media purge to delete expired Spaces objects.
- Add Alembic/Flask-Migrate and replace runtime schema changes with migrations.
- Create production App Platform app.
- Create Managed PostgreSQL database.
- Create Spaces bucket and configure CDN/public URL strategy.
- Configure production environment variables and secrets.
- Configure `SUPERADMIN_EMAILS=phil@pcp.dev`.
- Configure SMTP and verify feedback/admin notification email delivery.
- Create database backup and restore runbook.
- Create TrueNAS-to-DigitalOcean database migration runbook.
- Create TrueNAS-to-Spaces media migration runbook.
- Run the large pre-beta test deployment in `docs/large_test_deployment.md`.
- Add billing alert in DigitalOcean.
- Complete the owner checklist in `docs/launch_readiness.md`.

### Future Design Constraint

When designing new features, treat the app server as disposable. Store durable
customer data in PostgreSQL or object storage, not in the app container.

### Future Beta/Staging Environment

Status: deferred until Paceline has several active clubs or production usage
that justifies the cost.

The pre-master testing strategy is documented in
`docs/digitalocean_deployment.md`. For now, test `post-beta` locally and merge
to `master` only after automated tests and manual smoke checks pass.

When usage increases, create `beta.paceline.club` backed by the `post-beta`
branch with separate staging database, staging media storage, Stripe test keys,
and test OAuth/email configuration.

### Post-Dues Product Backlog

- Add a club store after Stripe Connect dues are complete. Clubs should be able
  to list jerseys, T-shirts, and similar items while payments run through the
  club's connected Stripe account.
