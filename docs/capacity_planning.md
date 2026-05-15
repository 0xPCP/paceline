# Capacity Planning — Paceline on DigitalOcean

Generated from a live Locust stress test against `https://paceline.club` (2026-05-14).

---

## Empirical baseline

**Setup:** DO basic-xs, 2 gunicorn sync workers, shared vCPU.  
**Test:** 1,000 simulated `AnonBrowser` users, 50/s spawn rate, 3-minute run.

| Locust concurrent users | Median latency | Assessment |
|---|---|---|
| 50 | ~950ms | Comfortable — users don't notice |
| 200 | ~1,800ms | Acceptable — slightly slow |
| 500 | ~4,000ms | Users notice |
| 1,000 | ~6,000ms | Queued — server at ceiling |
| **RPS ceiling** | **~38 RPS** | Hard wall for 2 sync workers |

Failure rate at 1,000 users: **0%** — the server queues rather than drops requests.

---

## Conversion to real-world users

Locust users click every 2–8s (avg 5s). Real users read pages for 20–30s.  
**1 real concurrent browser session ≈ 0.25 Locust users.**

Server is comfortable to ~50 Locust users → **~200 real simultaneous browsers**.

### Saturday morning spike model

The design load is the pre-ride rush: 30% of weekly-active members opening the app
in a 30-minute window. Average session: 5 minutes, 4 page views.

| Weekly-active members | Saturday spike (simultaneous sessions) | Locust-equivalent | Server state |
|---|---|---|---|
| 500 | ~150 | ~40 | ✅ Comfortable |
| 1,000 | ~300 | ~75 | ✅ Comfortable |
| 2,500 | ~750 | ~190 | ⚠️ Acceptable (p95 ~1.5s) |
| 5,000 | ~1,500 | ~375 | 🔴 Queuing (p95 ~3–4s) |
| 10,000 | ~3,000 | ~750 | 🔴 Saturated |

---

## Scaling tiers

### Tier 0 — Current (basic-xs, 2 workers)

- **Handles:** ~2,500–3,000 weekly-active members
- **RPS ceiling:** ~38 RPS
- **Config:** `WEB_CONCURRENCY=2`, `pool_size=3`, `max_overflow=1`
- **Cost:** ~$12/mo (app) + database
- **Action:** Nothing — this is the current state.

---

### Tier 1 — Free config change (basic-xs, 4 workers)

- **Handles:** ~4,000–5,000 weekly-active members
- **RPS ceiling:** ~76 RPS
- **What changes:** Set `WEB_CONCURRENCY=4` in DO app env vars. No instance upgrade.
- **DB pool adjustment required** (4 workers × 3 connections = 12 of 25 PG limit):

```python
# app/config.py
'pool_size': 2,
'max_overflow': 1,   # 4 workers × 3 = 12 connections — safe under 25-conn PG limit
```

- **Cost:** $0 increase

---

### Tier 2 — Instance upgrade (basic-s, 4 workers)

- **Handles:** ~10,000–12,000 weekly-active members
- **RPS ceiling:** ~100–120 RPS
- **What changes:** Upgrade `instance_size_slug: basic-s` in `.do/app.yaml` (dedicated vCPU).
  Dedicated core processes each request 1.5–2× faster than shared CPU.
- **DB:** Still fine — 4 workers × 3 connections = 12 connections.
- **Cost:** Check DO console for current pricing (~$25–50/mo range).
- **Trigger:** p95 consistently >2s on Saturday mornings.

---

### Tier 3 — Horizontal scaling (2 × basic-s instances)

- **Handles:** ~20,000–25,000 weekly-active members
- **RPS ceiling:** ~200–240 RPS
- **What changes:** Set `instance_count: 2` in `.do/app.yaml`. DO load-balances automatically.
- **Side effects requiring attention:**
  - Flask-Limiter rate limit state doesn't sync across instances — add Redis-backed storage
    (`RATELIMIT_STORAGE_URL: redis://...`). DO App Platform has a managed Redis add-on (~$15/mo).
  - DB: 2 instances × 4 workers × 3 connections = 24 connections — right at the 25-conn limit.
    Upgrade PG plan to the next connection tier at this point.
- **Cost:** ~2× Tier 2 + Redis add-on.

---

### Tier 4 — Async workers + bigger DB (professional tier)

- **Handles:** ~50,000–100,000 weekly-active members
- **RPS ceiling:** 500–1,000+ RPS
- **What changes:**
  - Switch to async gunicorn workers: `worker_class = 'gevent'`, `workers = 2`,
    `worker_connections = 100`. Each worker handles hundreds of concurrent I/O requests.
  - Upgrade to professional instance (dedicated multi-core).
  - Add Redis cache layer on `/discover/` and `/api/clubs/map-data` (60s TTL).
  - Database read replica for read-heavy routes.
- **Cost:** $100–300+/mo — this is a "good problem to have" tier.

---

## Signals that tell you it's time to scale

| Signal | Meaning | Action |
|---|---|---|
| DO App CPU consistently >70% | Workers CPU-bound | More workers or bigger instance |
| p95 >2s on `/discover/` or `/clubs/<slug>/` | DB queries backing up | Tier 1 (more workers) or check for missing index |
| Gunicorn `worker timeout` in logs | Request taking >60s | Investigate runaway query before scaling |
| DO "Request queue depth" metric rising | Connections waiting for a free worker | Tier 1 or Tier 2 |
| `OperationalError: connection pool exhausted` | Pool too small for worker count | Adjust `pool_size` per tier table above |

---

## Practical outlook

- **Tier 1** (4 workers, zero cost): probably needed around **5–10 clubs with active communities**.
- **Tier 2** (first paid upgrade): around **20–30 clubs**, or if a few large clubs each have 500+ weekly-active riders.
- **Tier 3+**: high-growth scenario — revisit when approaching Tier 2 ceiling.

The heaviest single route is `/discover/` (aggregates across all clubs). If it becomes a bottleneck
before a full tier upgrade is warranted, a 60-second in-memory cache on that query alone buys
significant headroom at zero infra cost.
