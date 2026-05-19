# DigitalOcean Deployment Model

## Decision

Paceline's planned production deployment model is DigitalOcean managed services:

- DigitalOcean App Platform for the Flask/Gunicorn web app.
- DigitalOcean Managed PostgreSQL for durable relational data.
- DigitalOcean Spaces for uploaded ride photos and other user media.
- SMTP provider configured through environment variables for email.
- GitHub-driven deployments with production secrets stored in DigitalOcean, not in the repo.

TrueNAS remains useful for local/dev deployment, but future production-oriented design should assume App Platform containers are disposable.

## Architecture

```text
Users
  -> HTTPS custom domain
  -> DigitalOcean App Platform
  -> Managed PostgreSQL
  -> Spaces object storage
  -> SMTP provider
```

Customer data must live outside the app container:

- PostgreSQL: users, clubs, rides, memberships, feedback, audit logs, media metadata.
- Spaces: uploaded ride photo files.
- App Platform: replaceable application code and runtime only.

## Required App Changes Before Production

### Media Storage

Current media storage uses the local filesystem through `UPLOAD_FOLDER`.
That is acceptable on TrueNAS but not for App Platform because containers can be rebuilt, replaced, or scaled.

Before DigitalOcean production cutover:

1. Add an S3-compatible storage adapter for DigitalOcean Spaces.
2. Store uploaded photos at keys like `ride_media/<ride_id>/<uuid>.jpg`.
3. Keep `RideMedia.file_path` as the object key.
4. Serve public media from Spaces/CDN or redirect to signed URLs.
5. Preserve private-club access checks before exposing private media.
6. Update nightly media purge to delete objects from Spaces.
7. Keep local filesystem storage available for tests and local dev.

### Database Migrations

Runtime schema guards are acceptable for the current dev deployment, but production should use explicit migrations.

Before DigitalOcean production cutover:

1. Add Alembic/Flask-Migrate.
2. Convert current schema to an initial migration.
3. Add migrations for `admin_audit_logs`, `site_feedback`, and future schema changes.
4. Update deploy procedure so migrations run before new app code receives traffic.
5. Take a Managed PostgreSQL backup before every schema-changing production deploy.

### Configuration

Production configuration should be environment-driven:

- `DATABASE_URL`
- `SECRET_KEY`
- `COOKIE_SECURE=true`
- `SUPERADMIN_EMAILS=phil@pcp.dev`
- `DONATE_URL`
- `STRIPE_SECRET_KEY`
- `STRIPE_CONNECT_WEBHOOK_SECRET` for the Stripe Connect webhook that listens to connected-account events
- `STRIPE_WEBHOOK_SECRET` only for optional platform-level Stripe events or fallback
- `STRIPE_PLATFORM_FEE_CENTS=100`
- `MAIL_SERVER`
- `MAIL_PORT`
- `MAIL_USE_TLS`
- `MAIL_USERNAME`
- `MAIL_PASSWORD`
- `MAIL_DEFAULT_SENDER`
- Spaces credentials and bucket settings:
  - `SPACES_BUCKET`
  - `SPACES_REGION`
  - `SPACES_ENDPOINT`
  - `SPACES_ACCESS_KEY`
  - `SPACES_SECRET_KEY`
  - `SPACES_PUBLIC_BASE_URL` if using a public/CDN URL

For automated club dues, Paceline creates direct charges on connected club
Stripe accounts. The Stripe webhook endpoint at `/stripe/webhook` must be
configured in Stripe Dashboard as a Connect webhook with **Listen to events on
connected accounts** enabled, otherwise checkout completion events will not
reach Paceline.

## Deployment Flow

Recommended production release flow:

1. Merge tested code to the production branch.
2. DigitalOcean App Platform builds a new app revision.
3. Run database migrations.
4. Start the new container against the existing Managed PostgreSQL database and Spaces bucket.
5. Run smoke checks:
   - `/`
   - `/clubs/`
   - `/discover/`
   - `/donate`
   - `/admin/`
   - `/admin/feedback/`
   - login/logout
   - ride signup
   - feedback email
   - photo upload and media serving
6. Promote traffic only after health checks pass.

## Data Migration From TrueNAS

### Database

Use `pg_dump` from the TrueNAS Postgres container and import into DigitalOcean Managed PostgreSQL.

High-level sequence:

1. Lower DNS TTL before final cutover.
2. Pause writes or schedule a maintenance window.
3. Export the TrueNAS database.
4. Import into DigitalOcean Managed PostgreSQL.
5. Run migrations.
6. Verify `phil@pcp.dev` is a superadmin.

### Media

Current media is under local `uploads/`.

High-level sequence:

1. Sync `uploads/ride_media/` to DigitalOcean Spaces.
2. Preserve object keys matching existing `RideMedia.file_path` values where possible.
3. Verify representative public and private media URLs.
4. Keep the TrueNAS media copy as rollback until production is stable.

## Cost Baseline

Expected initial monthly cost:

- App Platform 1 shared vCPU / 1 GiB: about $10-$12/month.
- Managed PostgreSQL 1 GiB: about $15/month.
- Spaces: $5/month, including 250 GiB storage and 1 TiB outbound transfer.

Expected starting total: about $30-$45/month depending on app container size.

Monitor:

- App Platform CPU/memory.
- Managed PostgreSQL connections, disk, cache hit ratio, and slow queries.
- Spaces storage and transfer.
- Paceline superadmin stats: usage, media count, storage warnings, feedback, and audit activity.

## Design Rule For Future Features

Future features must assume:

- App containers are disposable.
- User-generated files do not live permanently on local disk.
- Schema changes are migrated, not silently patched.
- Production secrets live in the host/platform secret manager.
- Customer data remains in Managed PostgreSQL and Spaces across app rebuilds.
