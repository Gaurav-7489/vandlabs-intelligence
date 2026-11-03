# PR #1 final engineering review (2026-11-03)

Scope: all 146 files. Method: artifact/credential sweep, route inventory, adversarial read of auth/tenancy/config/workflows, fixes verified by tests and CI.

## Fixed in this review
| # | Finding | Severity | Fix | Evidence |
|---|---|---|---|---|
| 1 | Render blueprint put the **owner (RLS-bypassing) DB URL in the API runtime** for `preDeployCommand` | High | Migrations moved to a gated GitHub job using `OWNER_DATABASE_URL`; Settings refuse staging/prod if a migration URL is present in runtime env | `test_owner_credentials_must_not_exist_in_runtime_env` |
| 2 | Production default CORS/CSRF origin list included `http://localhost:5173` | Medium | staging/prod require https origins | `test_non_https_or_localhost_cors_origin_rejected_in_production` |
| 3 | Session cookie lacked `__Host-` prefix | Low | `__Host-` whenever Secure | `test_host_prefixed_cookie_in_staging_and_production_only` |
| 4 | `/readyz` exposed dependency/AI/DB-role detail to anyone reaching the origin | Low | detail only for edge-authenticated callers | `test_readyz_hides_dependency_detail_from_non_edge_callers` |
| 5 | Worker did not run the unsafe-DB-role startup check | Medium | worker refuses unsafe roles in staging/prod | code + existing role tests |
| 6 | `BYPASSRLS` detection test **skipped in CI** | Medium (coverage) | `admin_sql` fixture uses the CI superuser; plus a test of the invariant itself (RLS hides rows from app role, BYPASSRLS role sees them) | CI runs `-rs`; 0 skips locally |
| 7 | **Logical backups impossible** under FORCE RLS as owner; partial file could masquerade as a backup | High (DR) | `vand_backup` read-only BYPASSRLS role + migration 0003 grants + restore drill in CI | `scripts/backup_restore_drill.sh` |
| 8 | ClamAV planned on a 2 GB instance; vendor docs say 4 GB | Medium (availability) | `render.yaml` → 4 GB plan, documented cost | docs/operations/staging-resource-plan.md |
| 9 | SPA API types hand-maintained with no contract check | Medium | contract test vs exported OpenAPI + CI freshness check | `src/lib/contract.test.ts` |
| 10 | CI e2e used fixed sleeps (failed once on a race) | Low | readiness waits (`scripts/wait_for.sh`) | CI |
| 11 | No dependency-update automation | Low | Dependabot (pip, npm, actions) | `.github/dependabot.yml` |

## Second review round (2026-11-03, after CI run #3)
| # | Finding | Severity | Fix | Evidence |
|---|---|---|---|---|
| 12 | `users` table had no RLS: a missing filter in tenant code could list every tenant's emails | Medium | Migration 0004: FORCE RLS; visible = self, current-tenant members, explicit identity step, platform; insert/update only in identity step; no DELETE | `test_users_rls_and_backup_role.py`, drill checks users isolation |
| 13 | Backup role scope | Info | Verified read-only (INSERT/UPDATE/DELETE/TRUNCATE denied) and refused as a runtime role | same file |
| 14 | Production image installed test/dev tooling (moto, pytest, mypy, pip-audit, Flask…) | Medium (supply chain) | `requirements.runtime.lock.txt` (52 pins); CI fails if it drifts from the tested lock — it immediately caught psycopg 3.3.7 vs tested 3.3.6 | `scripts/check_runtime_lock.py` |
| 15 | Neon URLs (`sslmode`, `channel_binding`) crash asyncpg; pooled endpoint needs unique prepared-statement names | High (would not start) | URL normalisation preserving TLS; pooler-safe engine options | `test_deploy_compat.py` (real queries in pooler mode) |
| 16 | boto3 ≥1.36 default checksums rejected by R2 in recent reports | Medium | checksums `when_required` | `test_r2_client_sends_checksums_only_when_required` |
| 17 | Render blueprint referenced an undefined env group; Key Value default `allkeys-lru` could evict rate-limit counters; container ignored `$PORT` | Medium | blueprint rewritten per spec; `noeviction`; `${PORT:-8000}` with exec | `render.yaml`, `Dockerfile` |
| 18 | Worker proxy forwarded the browser `Host` header; client IP relied on `CF-Connecting-IP` surviving a subrequest | Low | drop Host; explicit `X-Vand-Client-IP`, trusted only with `X-Origin-Auth` | `test_client_ip_header_only_trusted_from_edge`; `wrangler deploy --dry-run` OK |
| 19 | Restore tooling version mismatch (runner client 18 vs server 17) | Medium (DR) | drill version guard + client tools from the same `postgres:17` image | CI drill step |
| 20 | No SBOM | Low | CycloneDX SBOMs for production Python and shipped npm deps as CI artifacts | CI |
| 21 | UI lacked document reprocess/delete, session revocation, invite link, direct-task entry (APIs existed) | Low (UX) | added with two-step delete; e2e `ui_actions.mjs` | CI e2e |

| 22 | Provider DB URLs (`postgres://`, `postgresql://`) would select psycopg2 (not installed) for app, Alembic and CLI | High (would not start) | `with_driver()` normalisation | alembic + CLI run with a plain URL in tests |
| 23 | `backup-staging.yml` used Ubuntu's pg client 16, which cannot dump PG 17 | High (no backups) | client from `postgres:17` image | config review |
| 24 | Dockerfile HTTP HEALTHCHECK would mark the (HTTP-less) worker container unhealthy | Low | removed; platform checks `/healthz`, worker liveness via Redis heartbeat | — |
| 25 | Worker polled Postgres every second ⇒ Neon Free never scales to zero (~182 CU-h/month vs 100 limit ⇒ DB suspended mid-month) | High (staging outage) | Redis wake signal + Redis heartbeat; DB touched only on work, due retries, or sweep | `test_idle_worker_opens_no_db_sessions_and_wakes_on_new_work` (0 DB sessions while idle) |
| 26 | **Regression introduced by #25, caught before merge:** BLPOP on a client with a 1 s socket timeout abandoned the server-side wait; the next wake signal was swallowed and jobs waited for the sweep | High | dedicated blocking connection without socket timeout; Redis errors degrade to DB draining | `test_wake_signal_is_not_lost_after_long_idle` fails on the old code, passes on the fix |

**Limit stated explicitly:** tenant isolation via RLS uses transaction-scoped settings (`app.org_id`, `app.identity_resolution`). It protects against queries that *forget* a filter, not against arbitrary SQL injection inside the app role (an injected statement could also call `set_config`). Parameterized queries everywhere remain the primary SQLi control; there is no string-built SQL with user input in the codebase.

## Verified unchanged
No tracked runtime artifacts or credentials (only reviewed placeholders, each marked `pragma: allowlist secret` or in the baseline); dev token route mounted only in dev mode and Settings refuse dev mode in staging/prod; RLS FORCE on all tenant tables; audit append-only; approval separation of duties; idempotent verified execution; CSRF on all cookie-authenticated writes; Redis snapshot incident closed (history not rewritten).

## Accepted residual risks (documented, not fixed)
- GitHub Actions are pinned by major tag, not commit SHA (Dependabot now proposes updates; SHA pinning recommended before production).
- Python deps are version-pinned but not hash-pinned (`--require-hashes`); npm uses lockfile integrity hashes.
- Parser isolation is rlimits + netns (when allowed) + socket block, not a container/seccomp sandbox.
- IdP outage keeps existing sessions alive until the next successful revalidation.
