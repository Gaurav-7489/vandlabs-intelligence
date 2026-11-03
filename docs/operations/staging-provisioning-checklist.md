# Staging provisioning checklist (low-cost) — reconciled 2026-11-03 (Phase 1.7)

A checkbox or approval here is **not** proof that a resource exists. "Exists" below means the owner reported it as
verified in their own account; nothing in this file was provisioned from a Claude session (no Neon, Cloudflare,
Vercel, Auth0 or Render access was available to it). Full state table (approved/provisioned/configured/deployed/
live-verified) and the A4/A6 cost request: `docs/operations/phase-1-7-integration.md`. Prices: re-check before purchase.
Legend: **[YOU]** only the account owner can do it · **[CLAUDE]** can be done once access is granted.

## Approvals and actual state
| # | Scope | Approval | Actual state | Cost |
|---|---|---|---|---|
| A1 | Neon project `vandlabs-intelligence-staging` (id `shy-leaf-28061787`, PG 17, `aws-ap-southeast-1`, org `Gaurav`) | ✅ approved | **Exists** (owner-verified). Roles, migrations, RLS checks **not yet done** (step 2) | $0 Free |
| A2 | R2 buckets `vand-intel-staging-docs`, `vand-intel-staging-backups` + scoped tokens, existing Cloudflare account | ✅ approved (free tier) | Unknown — check before creating (step 3) | $0 within free tier |
| A3 | Cloudflare **frontend** Worker | ✅ approved (free) | **Superseded — do not deploy.** Vercel already hosts the SPA; `/api/v1/*` now goes through the Vercel gateway function (ADR 0007). `apps/web/worker/` is kept only as an optional future edge | — |
| A4 | Python API + worker hosting (Render Starter ×2, Hobby workspace) | ❌ **not approved** | Not created. **Blocks every live backend step** | $14/mo ($7 + $7, prorated); Hobby workspace ($0) supports workers/private services (Render docs) |
| A5 | Redis (Render Key Value Free) | ✅ approved (free) | **Deferred**: only reachable from Render services, so it is created together with A4 | $0 |
| A6 | ClamAV private service (Pro 4 GB), suspended outside test windows | ❌ **not approved** | Not created. Staging config refuses to start without a scanner | $85/mo prorated ≈ $0.116/h ⇒ ≈ $1.20 for 10 h/mo (suspended-state billing unconfirmed) |
| A7 | Auth0 staging tenant, **Free plan only** | ✅ approved (Free) | Unknown. If Free cannot require MFA → stop and ask; do not buy Essentials | $0 (Essentials $35/mo needs a new approval) |
| A8 | AI providers disabled (no keys) | ✅ approved | In effect by default (no keys in config) | $0 |
| A9 | Live 17-step acceptance run with synthetic users | ⏳ prepare only | Prepared and **rehearsed locally** (passes); live run needs approval after A4/A6 | — |

## Steps
1. **[YOU] GitHub**: give Claude push access (connect GitHub at https://claude.ai/connect-github and install the Claude GitHub App on `Gaurav-7489/vandlabs-intelligence`). Create environment `staging` with required reviewers. Branch protection on `main` (require `api`, `web`, `secrets`, `e2e`).
2. **[YOU/CLAUDE] Neon (A1, exists)** — do **not** create another project.
   - Console → project `shy-leaf-28061787` → Branches: confirm the default branch and database name (`neondb` unless renamed).
   - Compute → *Scale to zero*: on Free it is fixed at 5 min and cannot be disabled (Neon docs). `suspend_timeout_seconds: 0` in the creation response means "plan default" (not "never"); confirm the console shows 5 min. The idle worker does not poll Postgres (Redis BLPOP + 30 min sweep, `VAND_WORKER_IDLE_SWEEP_SECONDS=1800`), so compute can suspend.
   - **Branch first**: create a throwaway branch, run `infra/database/neon_bootstrap.sql` there as the project owner role over the direct endpoint (passwords via psql variables, see the file header), run migrations as `vand_owner` against `vand_staging`, then `scripts/verify_staging_db.sql` — every row `ok = t`. Delete the branch and repeat on the default branch with **new** generated passwords kept only in the secret manager.
   - The bootstrap's pre-flight row shows whether the owner role has BYPASSRLS. Without it, `vand_backup` cannot be created (PostgreSQL rule; tested): the script then fails atomically — **stop and report**, do not weaken RLS.
   - Record URLs in the secret manager only: direct `vand_owner` (migrations, GitHub env secret), pooled `vand_app` and `vand_worker` (Render), direct `vand_backup` (backup workflow).
3. **[YOU] R2 (A2)**: list buckets first; create only the two missing ones, private (no r2.dev public URL, no custom domain), location hint APAC. Tokens: (a) Object Read & Write on `vand-intel-staging-docs` only → API + worker; (b) Object Write on `vand-intel-staging-backups` only → backup workflow; (c) **restore** needs Object Read on backups — create it only when a restore drill runs, then revoke. Enable lifecycle rule on backups (e.g. delete after 35 days).
4. **[YOU] Auth0 (A7, Free)**: follow `docs/operations/auth0-setup.md`. First check Security → Multi-factor Auth: can OTP/WebAuthn be set to *Always*? Log in once with MFA and confirm the ID token has `amr: ["mfa"]`. If not available on Free → **stop**, report, do not weaken `VAND_REQUIRE_MFA_FOR_PRIVILEGED`. Application: Regular Web App; Allowed Callback `https://vandlabs-intelligence.vercel.app/api/v1/auth/callback`; Allowed Logout `https://vandlabs-intelligence.vercel.app/`; Web Origin same origin. Synthetic users: requester, approver, auditor, outsider (separate org), owner (MFA enrolled).
5. **[APPROVE A4 + A6] Python hosting**: see `docs/operations/phase-1-7-integration.md` §Hosting. With Render: connect repo, apply `render.yaml`, fill every `sync: false` var from the secret manager. Generate `VAND_SESSION_ENCRYPTION_KEY` (Fernet) and `VAND_ORIGIN_AUTH_SECRET` (≥ 32 random chars). Pooled Neon URLs + `VAND_DB_DISABLE_STATEMENT_CACHE=true`. No owner/migration URL in the runtime env (the app refuses to start).
6. **[CLAUDE] Migrations**: GitHub secret `STAGING_OWNER_DATABASE_URL` (Neon direct endpoint) → run *Deploy staging (manual)* → `migrate` (`alembic upgrade head`). Then `OWNER_DATABASE_URL=… python -m app.cli create-platform-admin <email>`. Verify `GET /readyz` (with `X-Origin-Auth`) ⇒ `db_role ok`.
7. **[YOU] Vercel (existing project — do not create another)**: Settings → Environment Variables, **Production scope only**: `VAND_API_ORIGIN=https://<API host>` and `VAND_ORIGIN_AUTH_SECRET=<same as API>`. Do not set them for Preview (the gateway refuses to proxy there unless `VAND_GATEWAY_ALLOW_PREVIEW=true`). Never use a `VITE_` prefix for either. Redeploy `main`. Confirm root directory `apps/web`, framework Vite, build `npm run build`, output `dist`.
8. **[YOU] Edge protections**: on `*.vercel.app` use Vercel Firewall rules if your plan has them (rate limit `/api/v1/auth/*`, `/api/v1/documents`); the API's own Redis-backed limits apply regardless. Full Cloudflare WAF needs a custom domain (not approved).
9. **[YOU] GitHub secrets for workflows**: `RENDER_DEPLOY_HOOK_API`, `RENDER_DEPLOY_HOOK_WORKER`, `STAGING_OWNER_DATABASE_URL`, `STAGING_BACKUP_DATABASE_URL`, `BACKUP_ENCRYPTION_PASSPHRASE`, `R2_BACKUP_ACCESS_KEY_ID`, `R2_BACKUP_SECRET_ACCESS_KEY`, `R2_ENDPOINT`; variables `STAGING_WEB_URL=https://vandlabs-intelligence.vercel.app`, `STAGING_API_URL=https://<API host>`. (Cloudflare Worker deploy secrets are no longer needed.)
10. **Post-deploy smoke test (part of deployment, non-destructive):** `tests/staging/live_checks.sh` only.
    **[CLAUDE, after A9 approval] Acceptance** — synthetic data only (full plan: phase-1-7-integration.md §A9):
    - `curl https://<API host>/api/v1/auth/session` ⇒ 403 (direct origin refused); `https://vandlabs-intelligence.vercel.app/api/v1/auth/session` ⇒ 200 `{"authenticated":false}`.
    - Preview deployment `/api/v1/auth/session` ⇒ 503 `gateway_unavailable`.
    - `tests/staging/acceptance.mjs` with `BASE_URL=https://vandlabs-intelligence.vercel.app IDP=auth0 EXPECT_SCAN=clean`.
    - `tests/staging/live_checks.sh` (WEB_URL, API_URL, PREVIEW_URL, ORIGIN_AUTH_SECRET in env): gateway, direct-origin 403, traversal, 413, preview 503, `/readyz` db_role.
    - `tests/staging/scanner_checks.mjs` with `OUTAGE=1`: EICAR quarantined + unsearchable; suspend ClamAV ⇒ `scan_pending`, unindexed; resume ⇒ processed automatically.
    - In the SPA, a 4.2 MB file ⇒ "larger than 4 MB … not uploaded".
    - `scripts/verify_staging_db.sql` on the default branch after migrations.
    - *Backup staging* once, restore into a Neon branch, run drill checks.
11. **[YOU] Rollback**: Vercel "Instant Rollback" to the previous production deployment; Render "rollback to previous deploy"; migrations are additive (0002–0004 downgrades exist; 0001 is destructive).

## Known operational limits
- Neon Free: cold start after ≥ 5 min idle; 100 CU-h/month cap ⇒ suspension (not billing) if exceeded.
- Render Key Value Free: no persistence — restart signs everyone out and resets counters.
- Vercel gateway: request/response bodies ≤ 4.5 MB ⇒ uploads capped at 4 MB.
- ClamAV suspended ⇒ uploads wait in `scan_pending` (never indexed unscanned).
- Single API and worker instance; no HA (staging only).

## Not in scope
Production resources, paid plans beyond A4/A6 once approved, a custom domain, real customer data, enabling AI providers.
