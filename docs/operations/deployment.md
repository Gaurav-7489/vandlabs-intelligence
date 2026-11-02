# Deployment (configuration prepared; NOTHING is deployed or externally verified)

Targets: Cloudflare Worker + static assets (`apps/web/wrangler.jsonc`, `worker/index.ts`), Render blueprint (`render.yaml`: API, worker, Key Value, private ClamAV), Neon Postgres, Cloudflare R2, Auth0 ([setup](auth0-setup.md)). Creating these resources **creates billable services and requires account owner authorization**.

## Order of operations
1. **Neon:** create staging project/database. As owner run `infra/database/roles.sql` equivalent with strong secret-managed passwords (plain roles via SQL, see ADR-0006). Record direct (migration) and pooled (runtime) URLs.
2. **R2:** private bucket + scoped token. **Auth0:** per auth0-setup.md. **Render:** apply blueprint, fill every `sync: false` variable.
3. First deploy runs `alembic upgrade head` (preDeploy, owner URL). Create the first platform admin once: `python -m app.cli create-platform-admin <email>` (run as a Render job/shell with the migration URL).
4. API refuses to start if: dev auth, dev DB hosts/credentials, local storage, missing OIDC/session/origin secrets, scanner not required, or an unsafe DB role. `/readyz` reports `database`, `redis`, `db_role`.
5. `wrangler secret put ORIGIN_AUTH_SECRET` (same value as `VAND_ORIGIN_AUTH_SECRET`), set `API_ORIGIN`, `wrangler deploy`.
6. Smoke test: `GET /api/v1/auth/config` → `{"mode":"oidc"}`, login, upload a CSV, see the insight, run the decision workflow, check `/readyz` from Render.

## Cloudflare edge (dashboard, not yet done)
Managed WAF ruleset; rate-limiting rules for `/api/v1/auth/login|callback` and `/api/v1/documents`; Bot Fight Mode / Turnstile only on the login entry; TLS Full (strict); always HTTPS; no caching rules for `/api/*` (the Worker also forces `Cache-Control: no-store`).

## Rollback
Render: redeploy previous deploy; Worker: `wrangler rollback`. Migrations are forward-compatible (expand/contract). `0001` downgrade is blocked without `VAND_ALLOW_DESTRUCTIVE_DOWNGRADE`; `0002` downgrade drops `insight_explanations` and scan columns.

## Backups / DR
**Not configured.** Enable Neon PITR + branch restore drill; R2 object versioning; define RPO/RTO before commitments. Redis holds sessions and rate counters only (loss = users re-login).

## Operations
Metrics/tracing/alerting are **not implemented** (JSON logs with request ids only; `GET /readyz`; `/usage/ai`; queue state in `jobs`). Parser isolation uses `unshare -rn` when the kernel allows it (reported by tests; GitHub runners and some hosts disable unprivileged user namespaces → falls back to rlimits + in-process socket block).
