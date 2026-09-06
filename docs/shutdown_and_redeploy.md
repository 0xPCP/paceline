# Paceline shutdown and redeployment

## Archived production state

The DigitalOcean App Platform service was retired on 2026-09-06 after a usage
review found no demonstrated organic production use. The public site contained
only the six-member demo club. App Platform metrics showed a steady request
baseline consistent with the configured 30-second `/health` check; Paceline did
not have first-party page-view analytics, so request metrics alone could not
identify unique human visitors.

The retired deployment used:

- GitHub repository `0xPCP/paceline`, branch `master`
- DigitalOcean App Platform app `paceline`
- App ID `38f554bf-ca59-4a8c-a20a-2b4d5bf96764`
- Custom domains `paceline.club` and `www.paceline.club`
- DigitalOcean Managed PostgreSQL cluster `paceline-db`
- DigitalOcean Spaces bucket `paceline-media`

The App Platform configuration was archived and its live components stopped.
The Managed PostgreSQL cluster and Spaces bucket were exported locally, their
backups were checksum-verified, and the original billable resources were then
deleted. Their former resource details are recorded in
`docs/provisioning_record.md`.

The private backup is not part of this Git repository. On the retirement
workstation it was stored at:

```text
/home/nullbnx/Projects/paceline-backups/2026-09-06/
```

It contains a PostgreSQL custom-format dump, every Spaces object under its
original key, checksum manifests, the archived DigitalOcean app spec, and a
restore README. Copy this directory to durable private backup storage before
relying on it long term.

## Redeploy from the DigitalOcean web UI

1. Open **App Platform**, select **Create App**, and choose GitHub as the source.
2. Select repository `0xPCP/paceline`, branch `master`, and enable automatic
   deployment on push.
3. Choose the Dockerfile build. Set the service name to `web`, HTTP port to
   `8080`, instance count to `1`, and size to `basic-xs` (or the current
   equivalent).
4. Configure `/health` as the HTTP health-check path, with a 30-second period.
5. Copy the non-secret runtime variables from `.do/app.yaml`.
6. Add the required secrets listed in `docs/restore_secrets.md`. Never commit
   their values or place placeholder secret values in `.do/app.yaml`.
7. Create a replacement PostgreSQL database and Spaces bucket, restore the
   private retirement backup, then set `DATABASE_URL` and the Spaces variables
   to the replacement resources. Follow `docs/production_cutover.md`.
8. Deploy, open the app console, and run `flask db upgrade`.
9. Add `paceline.club` as the primary domain and `www.paceline.club` as its
   alias. Apply the DNS records DigitalOcean displays.
10. Complete the smoke checks in `docs/digitalocean_deployment.md`, including
    login, club/ride pages, email, media, and the superadmin dashboard.

## Redeploy with `doctl`

Authenticate `doctl` to the intended DigitalOcean account, then run:

```bash
doctl apps create --spec .do/app.yaml
doctl apps list
```

The checked-in spec intentionally omits secret variables. Add the secrets in
the web UI before treating the deployment as production-ready. Then run the
database migration in the new app's console and restore the custom domains if
they were not created with the spec.

## Before deleting retained data

Export PostgreSQL with `pg_dump` and copy the Spaces bucket to independent
storage. Verify both backups before deleting either resource. Deleting the app,
database, or bucket is independent in DigitalOcean; stopping hosting does not
require deleting retained production data.
