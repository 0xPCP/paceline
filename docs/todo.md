# TODO

## Production Deployment: DigitalOcean

Status: planned.

The long-term production deployment model is documented in
`docs/digitalocean_deployment.md`. Future feature work should be compatible
with that model.

### Before Production Cutover

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
- Add production smoke-test checklist.
- Add billing alert in DigitalOcean.

## Demo Site

Status: scaffolded for isolated deployment.

The demo deployment model is documented in `docs/demo_deployment.md`.
Production should not be pre-populated with demo data. Use
`demo.paceline.club` with a separate app container, database, and media storage
for fictional sample clubs/rides.

- Configure `demo.paceline.club` DNS and Traefik/DigitalOcean routing.
- Add demo environment secrets.
- Run `scripts/seed_demo.py --yes` only with `PACELINE_DEMO_MODE=true`.
- Decide reset schedule for demo data.

### Future Design Constraint

When designing new features, treat the app server as disposable. Store durable
customer data in PostgreSQL or object storage, not in the app container.
