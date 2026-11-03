# Handoff — state as of 2026-11-03

## Where things stand
- **Repo:** `Gaurav-7489/vandlabs-intelligence`. Work branch `claude/peaceful-mendel-j30y5u`, PR #1 → `main`
  (https://github.com/Gaurav-7489/vandlabs-intelligence/pull/1), **ready for review, not merged**. Merge is the owner's decision.
- **Last verified head:** `ad320e4`, CI run 41589224358 — all four jobs green (`api`, `web`, `secrets`, `e2e`).
- **Nothing is provisioned or deployed.** No staging environment exists yet.
- **Next milestone:** a functioning, security-validated **staging** environment (not new features).

## What CI proves (job → evidence in logs)
| Job | Verified |
|---|---|
| api | ruff, mypy, 144 pytest (0 skipped) on Postgres 17 + Redis 7; backup/restore drill with pg 17 client/server (identical row counts, RLS forced, 23 policies, audit triggers, grants, app role sees 0 rows without tenant context); OpenAPI freshness; pip-audit clean (tested + runtime lock); runtime lock = 52 pins matching tested lock; CycloneDX SBOM |
| web | typecheck, lint, 58 vitest (contrast + SPA↔OpenAPI contract), build |
| secrets | detect-secrets vs `.secrets.baseline` |
| e2e | full workflow; UI actions 5/5 (direct task, reprocess, two-step delete, invite link, sign-out-everywhere); OIDC auth 8/8 against a local test issuer |

## NOT verified (needs live staging)
Auth0, Neon, R2, Render (incl. Docker image build there), Cloudflare edge/WAF, live ClamAV, live AI providers (AI stays disabled).

## Staging plan and costs (pricing checked 2026-11-03) — needs owner approval per item
Full steps: `docs/operations/staging-provisioning-checklist.md`; costs: `docs/operations/staging-resource-plan.md`.

| # | Resource (dedicated to VandLabs Intelligence) | Cost |
|---|---|---|
| A1 | New Neon project `vandlabs-intelligence-staging` (owner's free org, Singapore) | $0 (100 CU-h/mo; idle worker no longer keeps DB awake) |
| A2 | R2 buckets `vand-intel-staging-docs`, `vand-intel-staging-backups` + 2 scoped tokens | $0 in free tier |
| A3 | Worker `vandlabs-intelligence-web-staging` (workers.dev) | $0 |
| A4 | Render API + worker, Starter | **≈ $14/mo** |
| A5 | Render Key Value free (25 MB, `noeviction`) | $0 |
| A6 | Render ClamAV pserv 4 GB, suspended when not testing | **≈ $0.12/h; ≈ $85/mo if always on** |
| A7 | Auth0 staging tenant Free; B2C Essentials only if Free cannot enforce MFA | $0 or **$35/mo** |
| A8 | AI providers disabled | $0 |
| A9 | 17-step acceptance test (`tests/staging/acceptance.mjs`) with synthetic users | — |

Realistic total ≈ $14–16/mo (+$35 if Auth0 Essentials needed).

## Remaining production blockers
Everything under "NOT verified"; backups not yet scheduled against Neon; no alerting; external security review and load test.
Accepted residual risks (`docs/security/pr1-review.md`): Actions pinned by tag not SHA; Python deps not hash-pinned; parser sandbox
is rlimits + netns + socket block (not seccomp/container); IdP outage keeps sessions until next revalidation.

## Key design decisions worth knowing before changing code
- Migrations run only in the deploy job with `STAGING_OWNER_DATABASE_URL`; runtime services never get owner creds.
- Neon: URLs are normalized (`sslmode`/`channel_binding` → asyncpg `ssl`); `VAND_DB_DISABLE_STATEMENT_CACHE=true` for the pooler.
- Worker idles on Redis `BLPOP jobs:wake` using a **dedicated connection without socket timeout** (`redis_block`); heartbeat in
  `ops:worker:heartbeat`; Postgres touched only on wake, due retry, or sweep (`VAND_WORKER_IDLE_SWEEP_SECONDS`).
- Cloudflare Worker adds `X-Origin-Auth` (shared secret, ≥32 chars) and `X-Vand-Client-IP`; API trusts client IP only from the edge.
- Postgres version is 17 everywhere (CI, drill, backup workflow); the drill refuses mismatched client/server majors.
- Full history of findings and fixes: `docs/security/pr1-review.md` (26 findings). Incident: `docs/security/incident-2026-11-dump-rdb.md`.

## Suggested first steps in a new session
1. Read `CLAUDE.md`, this file, and `docs/operations/staging-provisioning-checklist.md`.
2. Confirm PR #1 status and that CI is still green on its head.
3. Ask the owner which approvals (A1–A9) are granted, then provision only those, following the checklist.
