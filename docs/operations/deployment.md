# Deployment (preparation only — nothing here has been deployed or verified)

## Targets
Frontend: Cloudflare (Workers static assets or Pages) serving `apps/web/dist`. API + worker: containers on a Python-capable host with a managed load balancer
(host not yet chosen). Database: Neon PostgreSQL. Objects: Cloudflare R2 (private bucket). Redis: managed instance (required for rate limiting; not optional).

## Order of operations
1. Create DB; run `infra/database/roles.sql` equivalent with **secret-managed passwords**; run `alembic upgrade head` as `vand_owner`.
2. Provision first platform admin: `python -m app.cli create-platform-admin <email>` (run with the migration URL).
3. Deploy API (`uvicorn app.main:create_app --factory`) with `VAND_ENV=production`; deploy ≥1 worker (`python -m app.worker`). Both are stateless; scale horizontally.
4. Health: `GET /healthz` (liveness), `GET /readyz` (DB + Redis; 503 when degraded).
5. Build frontend with `npm run build`; configure Cloudflare to proxy `/api/*` to the API origin; restrict the origin to Cloudflare IPs.

Startup refuses production with dev auth, dev DB credentials/hosts, or local object storage.

## Environment variables
See `.env.example` (all `VAND_*`). Separate secrets per environment. Neon pooled endpoint ⇒ `VAND_DB_DISABLE_STATEMENT_CACHE=true`; use the **direct** endpoint for migrations.

## Migrations & rollback
Forward-only in practice. `0001` downgrade drops the schema and is blocked unless `VAND_ALLOW_DESTRUCTIVE_DOWNGRADE=yes-i-understand`. Roll back application releases by redeploying the
previous image; write backward-compatible migrations (expand → migrate → contract).

## Backups / recovery
**Not configured.** Neon point-in-time restore and R2 versioning/replication must be enabled and a restore drill performed before launch; define RPO/RTO with the business first.

## Incident response (minimum)
Credential compromise: rotate DB/R2/AI/IdP secrets, revoke sessions at the IdP, review `audit_events` (append-only) for the window. Suspected tenant exposure: freeze uploads, preserve logs and DB snapshot,
identify affected org ids via audit `request_id`, notify per contract/law (obtain legal guidance; no compliance certification is claimed). Severity/escalation owners are **TBD by VandLabs**.

## Observability
JSON logs with `request_id` and secret redaction to stdout. Not yet implemented: metrics, tracing, error-monitoring backend, alerts, queue-depth dashboards (queue data is in the `jobs` table).
