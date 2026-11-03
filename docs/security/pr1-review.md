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

## Verified unchanged
No tracked runtime artifacts or credentials (only reviewed placeholders, each marked `pragma: allowlist secret` or in the baseline); dev token route mounted only in dev mode and Settings refuse dev mode in staging/prod; RLS FORCE on all tenant tables; audit append-only; approval separation of duties; idempotent verified execution; CSRF on all cookie-authenticated writes; Redis snapshot incident closed (history not rewritten).

## Accepted residual risks (documented, not fixed)
- `users` table has no RLS (emails readable by the app role); mitigated by app-level scoping and parameterized queries. Revisit with a `users` policy keyed to memberships.
- Actions are pinned by major tag, not commit SHA.
- Parser isolation is rlimits + netns (when allowed) + socket block, not a container/seccomp sandbox.
- IdP outage keeps existing sessions alive until the next successful revalidation.
