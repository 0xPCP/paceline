# Paceline Demo Deployment

The demo site should run at `demo.paceline.club` as a separate Paceline
deployment with fictional data only.

## Isolation Requirements

- Use a separate app container from production.
- Use a separate PostgreSQL database and volume.
- Use separate media storage.
- Do not reuse production OAuth credentials unless the demo redirect URI is
  explicitly approved.
- Do not configure Resend or SMTP for demo unless messages are routed to a test
  inbox with `EMAIL_RECIPIENT_OVERRIDE`.
- Never run `scripts/seed_demo.py` against production.

## TrueNAS Dev Demo

1. Create demo secrets in the TrueNAS project `.env`:

   ```text
   DEMO_DB_PASSWORD=<unique-password>
   DEMO_SECRET_KEY=<unique-secret-key>
   ```

2. Start the isolated demo stack:

   ```bash
   docker compose -f docker-compose.demo.yml up -d --build demo-db demo-web
   ```

3. Reset the fictional demo data:

   ```bash
   docker compose -f docker-compose.demo.yml exec demo-web python scripts/seed_demo.py --yes
   ```

4. Point `demo.paceline.club` at the TrueNAS/Traefik ingress.

The seed script requires `PACELINE_DEMO_MODE=true`, which is set only in
`docker-compose.demo.yml`.

## DigitalOcean Production Model

When Paceline moves to DigitalOcean, create the demo as a separate App Platform
app or component with its own Managed PostgreSQL database. The production app
should start empty except for `SUPERADMIN_EMAILS=phil@pcp.dev`; the demo app is
the only environment that should be seeded with fictional clubs and rides.

For repeatable demos, reset the demo database on a schedule, such as nightly or
before sales calls, by running:

```bash
python scripts/seed_demo.py --yes
```

only inside the demo app/container.
