# Handoff — state as of 2026-11-03 (Phase 1.7)

## Where things stand
- **GitHub:** Phase 1.7 was recovered from the verified archive and merged through [PR #14](https://github.com/Gaurav-7489/vandlabs-intelligence/pull/14). All API/web/secrets/e2e checks passed. The five recovered changesets have identical file trees; their new commit IDs and original IDs are mapped in that PR.
- **Gateway fix:** [PR #15](https://github.com/Gaurav-7489/vandlabs-intelligence/pull/15) fixes the deployed Node ESM helper import. All checks passed; merged as `112aee5`. A real Node ESM regression test now covers the startup boundary (88 frontend tests).
- **Vercel:** production deployment `dpl_3dqEZFyuZsUVjYZEYWJUJjvVdAc1` is READY. The homepage returns 200; `/api/v1/auth/config` returns the expected JSON 503 `gateway_unavailable` while backend configuration is absent. This proves gateway startup/fail-closed behaviour, not backend integration.
- **Neon:** project `shy-leaf-28061787` was verified directly (Free, PG 17, Singapore). The isolated SQL-bootstrap branch and the default `main` branch now have `vand_staging`, four dedicated SQL-created roles and migration head `0004`. All 28 verification rows pass on main. `vand_app` owns no tables, cannot create schema objects or bypass RLS, and sees zero documents/users without tenant context.
- **R2:** `vand-intel-staging-docs` and `vand-intel-staging-backups` were created in APAC; both have r2.dev access disabled and no custom domains. Scoped credentials and object round-trip/backup tests remain pending.
- **Still blocked:** Render is not connected here; paid A4/A6 resources have not been created. Auth0 tenant/application/MFA have not been configured or verified. Vercel has no gateway origin/secret environment variables yet. AI stays disabled; live acceptance A9 has not run. No paid services were created.

## Architecture (do not change without a decision)
Vercel (SPA + `/api/v1/*` gateway function, Node.js runtime, ADR 0007) → Render API + worker (+ Key Value, private
ClamAV) → Neon `vand_staging` · R2 private buckets · Auth0 Free (only if it can enforce MFA) · AI disabled.
No Cloudflare frontend Worker (A3 superseded).

## Approvals
A1 Neon ✅ reuse · A2 R2 ✅ free · A3 not required · **A4 Render API+worker ⏳** · A5 Key Value ✅ (with A4) ·
**A6 ClamAV ⏳** · A7 Auth0 ✅ Free only · A8 AI disabled ✅ · **A9 live acceptance ⏳**.
Costs and the state table: `docs/operations/phase-1-7-integration.md`.

## Verified locally on the Phase 1.7 candidate
ruff/mypy clean · 151 backend tests (PG 17 + Redis 7) · 87 web tests · build · OpenAPI current · runtime lock ok ·
detect-secrets clean · backup/restore drill · production image built and run · 17-step acceptance through the gateway
code with real ClamAV (test OIDC issuer) · live boundary checks vs local stack · real ClamAV suspend/resume.
**Cloud verification:** Neon schema/role/RLS checks, R2 bucket privacy, Vercel gateway startup and GitHub CI are now verified as above. Auth0, hosted API/worker/scanner, R2 object operations and the full live journey remain unverified.

## Key behaviours added in 1.7
- Gateway adds `X-Origin-Auth` server-side, refuses preview deployments and missing config, strips forged trust headers.
- Upload limit 4 MiB end to end (Vercel body limit 4.5 MB).
- Scanner holds: uploads wait unindexed while ClamAV is suspended; the worker PINGs clamd (no DB) and releases them
  automatically; holds retry every 30 min and expire after 7 days.
- Runtime DB roles may not be members of `neon_superuser` or any privileged role (startup check).
- Neon bootstrap `infra/database/neon_bootstrap.sql` + verification `scripts/verify_staging_db.sql` (branch first).

## Next steps
1. Connect Render and decide A4/A6 using the resource/cost request in `docs/operations/phase-1-7-integration.md`. No paid resources or billing changes were made.
2. Configure Auth0 Free and verify genuine MFA; if the required factors are unavailable, obtain a separate decision without weakening MFA.
3. Provision the approved backend, set scoped R2 credentials directly into the deployment/workflow secret stores, and retrieve the SQL-role connection strings securely from Neon. Do not create replacement roles through the Neon Console/API: they inherit `neon_superuser`.
4. Populate Vercel's Production-only gateway configuration after an API origin exists, then perform the approved smoke checks.
5. After A9 approval, run real-identity/storage/scanner acceptance and backup restoration. Create the first platform admin only for the confirmed intended identity.

## Database setup evidence
- Validation branch: `br-rough-flower-a14g38fj` (`phase-1-7-sql-bootstrap-validation`).
- Default staging branch: `br-young-resonance-a1e7teg7` (`main`).
- Applied the committed `0001`–`0004` migration upgrade statements as `vand_owner`, with the Alembic head recorded in the same transaction. Multi-command batches were split into individual PostgreSQL statements while preserving dollar-quoted function/DO blocks.
- Every row in `scripts/verify_staging_db.sql` passes: 16 tenant tables have ENABLED/FORCED RLS, runtime roles have no privileged memberships, backup has no writable table grants, and both append-only audit triggers exist.
- Passwords were generated independently for test/main and were not printed or committed. Neon resolves the SQL-created role credentials through its authenticated connection-string API.
- An earlier exploratory branch `br-muddy-poetry-a1lffhig` contains unused API-created roles and two SQL probe roles; it is not a runtime environment. The SQL probe login is disabled. Validation branches were retained; no branch or existing data was deleted.
