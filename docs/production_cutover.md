# Production Cutover Runbook

## Before you start

- All code changes are merged to `master` and pushed to GitHub.
- TrueNAS dev deployment is stable and has real data worth migrating.
- You have a DigitalOcean account with billing set up.
- DNS is managed via Cloudflare. You control the `paceline.club` zone.

---

## Step 1 — Provision DigitalOcean resources

### 1a. Managed PostgreSQL

1. Create a new PostgreSQL 16 cluster (1 GiB starter, 1 node — upgrade later).
2. Note the connection string: `postgresql://doadmin:<pw>@<host>:25060/defaultdb?sslmode=require`
3. In the cluster's "Users & Databases" panel, create database `paceline` and user `paceline`.
4. Note the `paceline` user's connection string — use this as `DATABASE_URL`.

### 1b. Spaces bucket

1. Create a Spaces bucket in the region closest to users (e.g. `nyc3`).
2. Name: `paceline-media` (or similar — name it once, it cannot change).
3. Permissions: **Private** (access is controlled via pre-signed URLs / CDN).
4. (Optional) Enable CDN on the bucket. Note the CDN endpoint URL.
5. Create a Spaces access key pair (API → Spaces Keys). Save both key and secret.
6. Note:
   - `SPACES_BUCKET=paceline-media`
   - `SPACES_REGION=nyc3`
   - `SPACES_ENDPOINT=https://nyc3.digitaloceanspaces.com`
   - `SPACES_ACCESS_KEY=...`
   - `SPACES_SECRET_KEY=...`
   - `SPACES_PUBLIC_BASE_URL=https://paceline-media.nyc3.cdn.digitaloceanspaces.com` (if CDN enabled)

### 1c. App Platform app

1. New App → GitHub → repo `0xPCP/paceline`, branch `master`.
2. Component type: **Web Service**.
3. Dockerfile detected automatically — confirm.
4. Plan: Basic, 1 shared vCPU / 1 GiB RAM ($12/mo).
5. Add all environment variables (see Step 2 below) before first deploy.
6. HTTP port: leave as App Platform default (`8080`) — the `$PORT` env var wires it up.
7. Health check path: `/`.

---

## Step 2 — Configure environment variables

Set these in App Platform's environment variable panel (encrypted at rest):

| Variable | Value |
|---|---|
| `DATABASE_URL` | Connection string from Step 1a |
| `SECRET_KEY` | New random 64-char string (`python3 -c "import secrets; print(secrets.token_hex(32))"`) |
| `COOKIE_SECURE` | `true` |
| `SUPERADMIN_EMAILS` | `phil@pcp.dev` |
| `EMAIL_PROVIDER` | `resend` |
| `RESEND_API_KEY` | From Resend dashboard |
| `MAIL_DEFAULT_SENDER` | `Paceline <noreply@paceline.club>` |
| `DONATE_URL` | Stripe payment link |
| `STRIPE_SECRET_KEY` | Paceline Stripe platform key, if Stripe Connect dues are enabled |
| `STRIPE_PUBLISHABLE_KEY` | Paceline Stripe publishable key, if Stripe Checkout/client flows are enabled |
| `STRIPE_CONNECT_WEBHOOK_SECRET` | Stripe Connect webhook signing secret for direct-charge dues events sent to `/stripe/webhook` |
| `STRIPE_WEBHOOK_SECRET` | Optional platform webhook signing secret for non-Connect Stripe events; kept as a fallback |
| `STRIPE_PLATFORM_FEE_CENTS` | `100` for the $1 Paceline platform fee on Stripe Connect dues |
| `SPACES_BUCKET` | `paceline-media` |
| `SPACES_REGION` | `nyc3` |
| `SPACES_ENDPOINT` | `https://nyc3.digitaloceanspaces.com` |
| `SPACES_ACCESS_KEY` | From Step 1b |
| `SPACES_SECRET_KEY` | From Step 1b |
| `SPACES_PUBLIC_BASE_URL` | CDN URL if enabled, otherwise blank |
| `GOOGLE_OAUTH_CLIENT_ID` | From Google Cloud Console |
| `GOOGLE_OAUTH_CLIENT_SECRET` | From Google Cloud Console |

---

### Stripe Connect webhook setup

Paceline uses Stripe Connect direct charges for automated club dues. In Stripe
Dashboard, create the `/stripe/webhook` endpoint as a **Connect webhook** by
choosing **Listen to events on connected accounts**. Subscribe at minimum to:

- `checkout.session.completed`
- `payment_intent.payment_failed`
- `charge.failed`

Copy that Connect endpoint's signing secret into
`STRIPE_CONNECT_WEBHOOK_SECRET`. A normal platform webhook secret is not enough
for direct-charge checkout events created on connected club accounts.

## Step 3 — Database migration (TrueNAS → Managed PostgreSQL)

### 3a. Lower DNS TTL

Set the `paceline.club` A/CNAME TTL to 60 seconds. Wait for the current TTL to expire.

### 3b. Maintenance window

Schedule a short write-pause (off-hours). Inform active clubs.

### 3c. Export from TrueNAS

```bash
ssh nullbnx@192.168.50.189
cd /mnt/fast/docker/projects/paceline
sg docker -c 'docker compose exec db pg_dump -U paceline paceline' > /tmp/paceline_export.sql
```

Copy to local machine:
```bash
scp nullbnx@192.168.50.189:/tmp/paceline_export.sql ./paceline_export.sql
```

### 3d. Import into Managed PostgreSQL

```bash
psql "postgresql://paceline:<pw>@<host>:25060/paceline?sslmode=require" < paceline_export.sql
```

### 3e. Run migrations

```bash
DATABASE_URL="postgresql://paceline:<pw>@<host>:25060/paceline?sslmode=require" \
  flask db upgrade
```

Verify:
```bash
psql "..." -c "\dt" | head -30
```

### 3f. Promote superadmin

The `SUPERADMIN_EMAILS` env var handles this automatically on first request. Verify after DNS cutover.

---

## Step 4 — Media migration (TrueNAS → Spaces)

### 4a. Install AWS CLI (S3-compatible)

```bash
pip install awscli
aws configure set aws_access_key_id <SPACES_ACCESS_KEY>
aws configure set aws_secret_access_key <SPACES_SECRET_KEY>
```

### 4b. Sync uploads to Spaces

```bash
aws s3 sync \
  /mnt/fast/docker/projects/paceline/uploads/ride_media/ \
  s3://paceline-media/ride_media/ \
  --endpoint-url https://nyc3.digitaloceanspaces.com \
  --acl private
```

### 4c. Verify representative files

```bash
# List a few objects
aws s3 ls s3://paceline-media/ride_media/ \
  --endpoint-url https://nyc3.digitaloceanspaces.com --recursive | head -20

# Generate a pre-signed URL and open in browser
aws s3 presign s3://paceline-media/ride_media/<ride_id>/<file.jpg> \
  --endpoint-url https://nyc3.digitaloceanspaces.com --expires-in 300
```

---

## Step 5 — End-to-end smoke test on TrueNAS with Spaces credentials

Before cutting DNS, verify the code + Spaces work together on TrueNAS:

1. Add Spaces credentials to TrueNAS `.env`:
   ```
   SPACES_BUCKET=paceline-media
   SPACES_REGION=nyc3
   SPACES_ENDPOINT=https://nyc3.digitaloceanspaces.com
   SPACES_ACCESS_KEY=...
   SPACES_SECRET_KEY=...
   ```
2. Rebuild and restart:
   ```bash
   ssh nullbnx@192.168.50.189
   cd /mnt/fast/docker/projects/paceline
   sg docker -c 'docker compose up -d --build'
   ```
3. Run the smoke checklist below against `https://cyclingclub.pcp.dev`.

---

## Step 6 — Smoke test checklist

For the full pre-beta rehearsal, use `docs/large_test_deployment.md`. The list
below is the shorter cutover smoke check to run during production deployment.

Run these checks against the target deployment (TrueNAS+Spaces pre-cutover, then again post-cutover on App Platform).

### Auth
- [ ] Register a new user
- [ ] Log in / log out
- [ ] Password reset email delivered
- [ ] Google OAuth (if configured)

### Club & rides
- [ ] Home page loads, upcoming rides visible
- [ ] `/clubs/` lists clubs
- [ ] `/discover/` map renders
- [ ] Club detail page loads
- [ ] Ride detail page loads
- [ ] Sign up for a ride
- [ ] Download `.ics` file
- [ ] Download GPX (if ride has route URL)

### Media — local storage path
- [ ] Upload a photo to a past ride (only required pre-cutover on TrueNAS)
- [ ] Photo appears in ride detail media section
- [ ] Photo serves correctly via `/media/ride/<id>/<filename>`

### Media — Spaces path (after Spaces credentials set)
- [ ] Upload a photo to a past ride
- [ ] Photo appears in ride detail
- [ ] Response is a 302 redirect to a pre-signed or CDN URL
- [ ] Delete the photo — gone from DB and Spaces
- [ ] Upload photo on a **private** club ride — confirms membership check runs

### Board
- [ ] Post to club board
- [ ] Photo attachment on board post serves correctly
- [ ] Reply to a post

### Admin
- [ ] `/admin/` superadmin dashboard loads
- [ ] Club admin dashboard loads
- [ ] Feedback email delivered to `phil@pcp.dev`
- [ ] Member approval flow (if manual-approval club)
- [ ] CSV member export downloads

### Email
- [ ] Ride cancellation email (cancel a test ride)
- [ ] Weekly digest (trigger manually via `flask shell` if needed)

### Performance / errors
- [ ] No 500 errors in App Platform logs during the above flows
- [ ] App Platform metrics: CPU < 50%, memory < 80%

---

## Step 7 — DNS cutover

1. Verify smoke test passes on App Platform.
2. Add a custom domain in App Platform: `paceline.club` and `www.paceline.club`.
3. App Platform will show the DNS record to add (CNAME to the App Platform ingress).
4. In Cloudflare, update/add the CNAME. Set proxy status to **DNS only** (grey cloud) initially so you can verify propagation.
5. Wait for propagation (`dig paceline.club`).
6. Re-run smoke test against `https://paceline.club`.
7. Flip Cloudflare proxy back to **Proxied** (orange cloud) for DDoS protection + caching.

---

## Step 8 — Post-cutover

- Set up DigitalOcean Alerts:
  - App Platform: CPU > 80% for 5 min → email
  - Managed PostgreSQL: disk > 80% → email
  - Spaces: bandwidth > 800 GiB/month → email
- Keep TrueNAS deployment running for 1 week as a rollback target.
- Increase DNS TTL back to 300s or higher once stable.

---

## Rollback

If something breaks after DNS cutover:

1. Point DNS back to the Cloudflare Tunnel / TrueNAS IP.
2. Revert `SPACES_BUCKET` on TrueNAS to empty (back to local filesystem).
3. Investigate App Platform logs.
4. Do not delete the Managed PostgreSQL cluster or Spaces bucket during rollback — the data is still valid.
