# Paceline Pulse Health Monitoring

This document describes **Paceline Pulse**, the lightweight TrueNAS/Docker
health and latency monitor for the live Paceline site.

## Purpose

Run a small container outside the Paceline app that checks the public production
health endpoint and emails `phil@pcp.dev` if the site appears down or becomes
too slow.

The monitor is intentionally independent of Flask and the production database.
If the Paceline app or database is down, the monitor can still send email through
Resend directly.

Paceline Pulse also includes a small read-only dashboard UI for checking the
current status from the TrueNAS network.

## What It Checks

Default URL:

```text
https://paceline.club/health
```

Default behavior:

- Check every 60 seconds.
- Treat HTTP `2xx` and `3xx` as healthy.
- Alert after 3 consecutive failures.
- Alert after 3 consecutive slow checks above 3000 ms.
- Repeat down alerts at most every 30 minutes while the outage continues.
- Send recovery emails when the site becomes healthy or latency returns under
  the threshold.
- Persist state in a Docker volume so container restarts do not create alert
  loops.
- Record recent check history for latency and uptime trends.

## Dashboard

The dashboard runs inside the same container on port `8080`.

Production dashboard URL:

```text
https://paceline-pulse.pcp.dev/
```

This is exposed through the existing TrueNAS Cloudflare Tunnel and Traefik
stack, not by opening an inbound port on the TrueNAS firewall.

If TrueNAS maps the container port directly for LAN-only testing, the local URL
will be:

```text
http://<truenas-host-or-ip>:8080/
```

For example:

```text
http://192.168.50.189:8080/
```

The dashboard shows:

- green/yellow/red current status
- latest latency
- rolling uptime percentage
- average latency
- p95 latency
- max latency
- slow check count
- failure count
- last success/failure timestamps
- a visual trend of the last checks

Green means the health endpoint is passing and latency is below the configured
threshold. Yellow means the site is reachable but slow. Red means the health
check is failing or an outage alert is active.

Set `MONITOR_DASHBOARD_USERNAME` and `MONITOR_DASHBOARD_PASSWORD` to require
basic auth at the container. For the public hostname, also protect
`paceline-pulse.pcp.dev` with Cloudflare Access so only approved users can open
the dashboard.

## Cloudflare Tunnel Setup

Paceline Pulse follows the existing TrueNAS pattern:

- the infrastructure stack runs `cloudflared`
- `cloudflared` sends traffic to Traefik
- each app joins the external `traefik` Docker network
- each app advertises its hostname and port with Traefik labels

Paceline Pulse does not run its own `cloudflared` sidecar.

The repo includes a dedicated compose file:

```bash
docker compose -f docker-compose.pulse.yml up -d --build
```

Required environment variables:

```text
RESEND_API_KEY=...
MONITOR_DASHBOARD_USERNAME=...
MONITOR_DASHBOARD_PASSWORD=...
```

Required TrueNAS/Cloudflare setup:

1. Confirm the existing infrastructure compose is running the shared
   `cloudflared` tunnel and Traefik reverse proxy.
2. Confirm the external Docker network exists:
   ```bash
   docker network ls | grep traefik
   ```
3. Add a Cloudflare Tunnel public hostname:
   ```text
   paceline-pulse.pcp.dev
   ```
4. Route that hostname to the existing Traefik service, matching the other
   `*.pcp.dev` apps on TrueNAS.
5. Paceline Pulse's compose labels route the hostname internally:
   ```text
   Host(`paceline-pulse.pcp.dev`) -> paceline-pulse:8080
   ```
6. Create a Cloudflare Access self-hosted application for:
   ```text
   https://paceline-pulse.pcp.dev
   ```
7. Add an Access policy that only allows approved admin email addresses.
8. Keep the `MONITOR_DASHBOARD_USERNAME` and `MONITOR_DASHBOARD_PASSWORD`
   enabled as a second layer of protection.

## Email Provider

The monitor uses Resend directly with the same Paceline sending domain.

Required:

```text
RESEND_API_KEY=...
MAIL_DEFAULT_SENDER=Paceline Monitor <noreply@paceline.club>
MONITOR_ALERT_TO=phil@pcp.dev
```

The down alert subject is intentionally loud:

```text
[CRITICAL] PACELINE.CLUB IS DOWN - IMMEDIATE ATTENTION REQUIRED
```

Latency alerts use:

```text
[WARNING] PACELINE.CLUB IS SLOW - LATENCY DEGRADED
```

The email includes:

- monitored URL
- timestamp
- monitor container host
- consecutive failure count
- HTTP status code
- elapsed request time
- error message
- last successful check time
- response excerpt, if any
- suggested debugging steps

## TrueNAS Docker Compose Example

Build the monitor image from the Paceline repo:

```bash
docker build -f Dockerfile.monitor -t paceline-health-monitor:latest .
```

Example compose service:

```yaml
services:
  paceline-health-monitor:
    image: paceline-health-monitor:latest
    container_name: paceline-pulse
    restart: unless-stopped
    environment:
      MONITOR_URL: "https://paceline.club/health"
      MONITOR_INTERVAL_SECONDS: "60"
      MONITOR_TIMEOUT_SECONDS: "10"
      MONITOR_FAILURES_BEFORE_ALERT: "3"
      MONITOR_LATENCY_ALERT_MS: "3000"
      MONITOR_LATENCY_FAILURES_BEFORE_ALERT: "3"
      MONITOR_ALERT_COOLDOWN_SECONDS: "1800"
      MONITOR_ALERT_TO: "phil@pcp.dev"
      RESEND_API_KEY: "${RESEND_API_KEY}"
      RESEND_API_URL: "https://api.resend.com/emails"
      RESEND_TIMEOUT_SECONDS: "10"
      MAIL_DEFAULT_SENDER: "Paceline Monitor <noreply@paceline.club>"
      MONITOR_DASHBOARD_ENABLED: "true"
      MONITOR_DASHBOARD_PORT: "8080"
      MONITOR_DASHBOARD_USERNAME: "${MONITOR_DASHBOARD_USERNAME:-}"
      MONITOR_DASHBOARD_PASSWORD: "${MONITOR_DASHBOARD_PASSWORD:-}"
    ports:
      - "8080:8080"
    volumes:
      - paceline_health_monitor_state:/state

volumes:
  paceline_health_monitor_state:
```

For the Cloudflare Tunnel deployment, prefer `docker-compose.pulse.yml` instead
of this single-container example. The dedicated compose file joins the existing
external `traefik` network and uses Traefik labels for
`paceline-pulse.pcp.dev`.

## Optional Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `MONITOR_URL` | `https://paceline.club/health` | URL to check |
| `MONITOR_EXPECTED_TEXT` | empty | Optional text that must appear in the response body |
| `MONITOR_INTERVAL_SECONDS` | `60` | Seconds between checks |
| `MONITOR_TIMEOUT_SECONDS` | `10` | HTTP timeout per check |
| `MONITOR_FAILURES_BEFORE_ALERT` | `3` | Consecutive failures before first down email |
| `MONITOR_LATENCY_ALERT_MS` | `3000` | Milliseconds before a healthy response is considered slow; set `0` to disable latency alerts |
| `MONITOR_LATENCY_FAILURES_BEFORE_ALERT` | `3` | Consecutive slow checks before latency email |
| `MONITOR_ALERT_COOLDOWN_SECONDS` | `1800` | Minimum seconds between repeated down alerts |
| `MONITOR_ALERT_TO` | `phil@pcp.dev` | Comma-separated alert recipients |
| `MONITOR_STATE_PATH` | `/state/paceline-pulse.json` | Persistent state file |
| `MONITOR_HISTORY_PATH` | `/state/paceline-pulse-history.json` | Persistent check history file |
| `MONITOR_HISTORY_LIMIT` | `1440` | Number of recent checks retained for dashboard trends |
| `MONITOR_DASHBOARD_ENABLED` | `true` | Enable the dashboard UI |
| `MONITOR_DASHBOARD_HOST` | `0.0.0.0` | Dashboard bind address inside the container |
| `MONITOR_DASHBOARD_PORT` | `8080` | Dashboard port inside the container |
| `MONITOR_DASHBOARD_USERNAME` | empty | Optional basic-auth username |
| `MONITOR_DASHBOARD_PASSWORD` | empty | Optional basic-auth password |
| `RESEND_API_KEY` | required | Resend API key |
| `RESEND_API_URL` | `https://api.resend.com/emails` | Resend email API endpoint |
| `MAIL_DEFAULT_SENDER` | `Paceline Monitor <noreply@paceline.club>` | From address |

## First Test

After starting the container:

1. Check logs:
   ```bash
   docker logs -f paceline-pulse
   ```
2. Confirm logs show `OK`.
3. Open the dashboard:
   ```text
   https://paceline-pulse.pcp.dev/
   ```
4. Confirm the dashboard shows green status and current latency.
5. Temporarily set `MONITOR_URL` to an invalid URL and restart the container.
6. Wait for 3 failed checks.
7. Confirm the dashboard turns red and the critical alert email arrives.
8. Restore `MONITOR_URL=https://paceline.club/health`.
9. Confirm the dashboard returns green and the recovery email arrives.

Do not leave the monitor pointed at an invalid URL after testing.

To test latency alerting without waiting for a real slowdown, temporarily set
`MONITOR_LATENCY_ALERT_MS=1`, restart the container, and wait for the configured
number of slow checks. Restore the normal threshold afterward.
