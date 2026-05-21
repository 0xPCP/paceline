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
    volumes:
      - paceline_health_monitor_state:/state

volumes:
  paceline_health_monitor_state:
```

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
3. Temporarily set `MONITOR_URL` to an invalid URL and restart the container.
4. Wait for 3 failed checks.
5. Confirm the critical alert email arrives.
6. Restore `MONITOR_URL=https://paceline.club/health`.
7. Confirm the recovery email arrives.

Do not leave the monitor pointed at an invalid URL after testing.

To test latency alerting without waiting for a real slowdown, temporarily set
`MONITOR_LATENCY_ALERT_MS=1`, restart the container, and wait for the configured
number of slow checks. Restore the normal threshold afterward.
