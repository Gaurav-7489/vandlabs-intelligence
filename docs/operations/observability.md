# Observability (staging-sized)

**Implemented & tested:** hourly counters in Redis + a worker-published queue snapshot, read via `GET /api/v1/ops/metrics` (VandLabs platform admin + MFA only; aggregates only, no tenant ids/content). JSON logs to stdout with `request_id`, secret redaction, no document contents.

| Signal | Source | Counter / field |
|---|---|---|
| API errors & latency | request middleware | `http.2xx/4xx/5xx`, `latency_histogram_ms` (≤50,100,250,500,1000,5000,>5000) |
| Failed authentication | identity layer, OIDC callback | `auth.failure`, `auth.login_failed` |
| Rate-limit violations | limiter | `ratelimit.violation.<policy>` |
| Storage failures | upload path | `storage.error` |
| Document processing | worker | `documents.failed`, `documents.quarantined`, `scan.unavailable` |
| Worker failures | worker | `jobs.completed`, `jobs.failed`, `jobs.dead_letter` |
| Queue depth / age | worker snapshot every 30 s | `queue.by_status`, `queued_oldest_age_seconds`, `worker_stale` (>90 s ⇒ worker down) |
| AI usage | gateway | `ai.calls`, `ai.failed`, `ai.tokens` (+ per-org `/usage/ai`) |
| DB health / role safety | `/readyz` (detail only for edge-authenticated callers) | `database`, `redis`, `db_role` |

**Not configured (needs accounts):** alert delivery. Suggested thresholds are returned by the endpoint (`thresholds`): 5xx > 20/h, auth failures > 100/h, rate-limit violations > 500/h, any dead letter, oldest queued job > 300 s, `worker_stale`. Cheapest wiring: Render health checks + a scheduled GitHub Action that polls `/ops/metrics` with a dedicated platform-admin service credential and opens an issue/notifies on breach. Error tracking (e.g. Sentry free tier) is not integrated.

**Ownership:** TBD by VandLabs (on-call owner, escalation contact). Counters reset if Redis restarts (Render free Key Value has no persistence).
