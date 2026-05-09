# Paceline — Production Provisioning Record

Provisioned: 2026-05-09  
Region: `nyc3` / App Platform region `nyc`  
Account: pcporte.dd@gmail.com

---

## Resources created

### Managed PostgreSQL

| Field | Value |
|---|---|
| Cluster ID | `dcd73714-40ce-4dc2-acbf-242cf141033a` |
| Cluster name | `paceline-db` |
| Engine | PostgreSQL 16 |
| Size | `db-s-1vcpu-1gb` (1 shared vCPU, 1 GiB RAM, 10 GiB SSD) |
| Nodes | 1 (single node — add a standby if uptime SLA is required) |
| Region | nyc3 |
| Host | `paceline-db-do-user-593559-0.f.db.ondigitalocean.com` |
| Port | 25060 (TLS required) |
| Database | `paceline` |
| User | `paceline` |
| Cost | ~$15/month |

**DATABASE_URL format:**
```
postgresql://paceline:<password>@paceline-db-do-user-593559-0.f.db.ondigitalocean.com:25060/paceline?sslmode=require
```
The password is stored as a secret in the App Platform app (not in this file).

**`doctl` reference:**
```bash
doctl databases get dcd73714-40ce-4dc2-acbf-242cf141033a
doctl databases connection dcd73714-40ce-4dc2-acbf-242cf141033a
```

---

### Spaces Object Storage

| Field | Value |
|---|---|
| Bucket name | `paceline-media` |
| Region | nyc3 |
| S3 endpoint | `https://nyc3.digitaloceanspaces.com` |
| CDN | Not enabled (set `SPACES_PUBLIC_BASE_URL` if you add CDN later) |
| Cost | $5/month (250 GiB storage + 1 TiB transfer included) |

#### Spaces keys

| Name | Access Key | Scope | Purpose |
|---|---|---|---|
| `paceline-media-key` (fullaccess) | `DO00YGCVTZKFH4XUAW9J` | all buckets | Admin key — used to create the bucket. Rotate or delete after setup is stable. |
| `paceline-app-key` (readwrite) | `DO8019NMZH4EX4Q8GMHK` | `paceline-media` only | Runtime key — used by the app to upload/serve/delete photos. Stored as `SPACES_ACCESS_KEY` secret in App Platform. |

> **Security note:** The fullaccess key (`DO00YGCVTZKFH4XUAW9J`) should be rotated or deleted once the deployment is stable and you're confident the scoped app key works. Keep only the scoped `readwrite` key for day-to-day operations.

**`doctl` reference:**
```bash
doctl spaces keys list
doctl spaces keys delete DO00YGCVTZKFH4XUAW9J   # delete admin key when done
```

---

### App Platform

| Field | Value |
|---|---|
| App ID | `38f554bf-ca59-4a8c-a20a-2b4d5bf96764` |
| App name | `paceline` |
| Region | nyc |
| Source | GitHub `0xPCP/paceline` branch `master` |
| Deploy on push | yes |
| Instance | `basic-xs` (1 shared vCPU, 1 GiB RAM) |
| Instance count | 1 |
| HTTP port | 8080 (App Platform injects `PORT=8080`) |
| Cost | ~$10/month |

**`doctl` reference:**
```bash
doctl apps get 38f554bf-ca59-4a8c-a20a-2b4d5bf96764
doctl apps list-deployments 38f554bf-ca59-4a8c-a20a-2b4d5bf96764
doctl apps logs 38f554bf-ca59-4a8c-a20a-2b4d5bf96764 --type=run
```

#### Environment variables set

| Variable | Type | Value / Notes |
|---|---|---|
| `COOKIE_SECURE` | plain | `true` |
| `SUPERADMIN_EMAILS` | plain | `phil@pcp.dev` |
| `MAIL_DEFAULT_SENDER` | plain | `Paceline <noreply@paceline.club>` |
| `EMAIL_PROVIDER` | plain | `resend` |
| `SPACES_BUCKET` | plain | `paceline-media` |
| `SPACES_REGION` | plain | `nyc3` |
| `SPACES_ENDPOINT` | plain | `https://nyc3.digitaloceanspaces.com` |
| `SPACES_PUBLIC_BASE_URL` | plain | `` (empty — add CDN URL here if enabled) |
| `DATABASE_URL` | **secret** | stored encrypted in DO |
| `SECRET_KEY` | **secret** | stored encrypted in DO |
| `RESEND_API_KEY` | **secret** | stored encrypted in DO |
| `SPACES_ACCESS_KEY` | **secret** | stored encrypted in DO |
| `SPACES_SECRET_KEY` | **secret** | stored encrypted in DO |
| `GOOGLE_OAUTH_CLIENT_ID` | **secret** | stored encrypted in DO |
| `GOOGLE_OAUTH_CLIENT_SECRET` | **secret** | stored encrypted in DO |

---

## Monthly cost summary

| Resource | Size | $/month |
|---|---|---|
| Managed PostgreSQL | db-s-1vcpu-1gb, 1 node | ~$15 |
| Spaces | 250 GiB + 1 TiB egress | ~$5 |
| App Platform | basic-xs, 1 instance | ~$10 |
| **Total** | | **~$30/month** |

---

## Pending manual step — run database migrations

The app will fail on first request until the schema is applied. After the first deployment succeeds:

```bash
# Get a one-off console session via doctl
doctl apps console 38f554bf-ca59-4a8c-a20a-2b4d5bf96764 --component web

# Inside the console:
flask db upgrade
exit
```

Or run migrations directly against the Managed PG connection string from your local machine:

```bash
DATABASE_URL="postgresql://paceline:<pw>@paceline-db-do-user-593559-0.f.db.ondigitalocean.com:25060/paceline?sslmode=require" \
  /home/nullbnx/Projects/paceline/.venv/bin/python3 -m flask db upgrade
```

---

## Next steps

1. **Watch first build:** `doctl apps logs 38f554bf-ca59-4a8c-a20a-2b4d5bf96764 --type=build --follow`
2. **Run migrations** (see above) once the app is deployed and the DB is reachable.
3. **Seed superadmin** — the `SUPERADMIN_EMAILS=phil@pcp.dev` env var promotes the account automatically on first request.
4. **Run smoke test checklist** from `docs/production_cutover.md` against the App Platform URL.
5. **Add custom domain** in the DO console (Apps → paceline → Settings → Domains).
6. **Migrate TrueNAS data** if needed — see `docs/production_cutover.md` Steps 3 and 4.
7. **Delete the fullaccess Spaces key** (`DO00YGCVTZKFH4XUAW9J`) once everything is stable.
8. **Set up billing alerts** in DO: CPU > 80%, PG disk > 80%, Spaces > 200 GiB.

---

## Scaling playbook

| Trigger | Action |
|---|---|
| App memory > 80% sustained | Scale instance to `basic-s` (2 GiB, +$10/mo) |
| PG CPU > 80% or connections > 80% | Resize to `db-s-1vcpu-2gb` (+$15/mo) |
| PG disk > 8 GiB | Expand storage (online, no downtime) |
| Traffic spikes | Increase `instance_count` to 2 (double app cost) |
| Uptime SLA needed | Add PG standby node (doubles PG cost) |
