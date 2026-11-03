# Handoff — state as of 2026-11-03 (Phase 1.7)

## Where things stand
- **Repo:** `Gaurav-7489/vandlabs-intelligence`. `main` = `8356598` (PR #1 merged earlier; Vercel SPA routing on top).
- **Work branch:** `feat/phase-1-7-cloud-integration` (Phase 1.7). **Not pushed from Claude** — the session had read-only
  GitHub access; it was delivered as a git bundle + patches. Once pushed, open a PR to `main`; merging is the owner's call.
- **Live:** only the SPA on the existing Vercel project (https://vandlabs-intelligence.vercel.app). It cannot reach an API
  until the gateway is merged/deployed and an API host exists.
- **Neon:** project `shy-leaf-28061787` exists (owner-reported). Roles/DB/migrations not applied.
- **Nothing else is provisioned.** No spend.

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
**Not verified:** Auth0, Neon, R2, Render, Vercel runtime/env scoping, CI on the new branch (not pushed).

## Key behaviours added in 1.7
- Gateway adds `X-Origin-Auth` server-side, refuses preview deployments and missing config, strips forged trust headers.
- Upload limit 4 MiB end to end (Vercel body limit 4.5 MB).
- Scanner holds: uploads wait unindexed while ClamAV is suspended; the worker PINGs clamd (no DB) and releases them
  automatically; holds retry every 30 min and expire after 7 days.
- Runtime DB roles may not be members of `neon_superuser` or any privileged role (startup check).
- Neon bootstrap `infra/database/neon_bootstrap.sql` + verification `scripts/verify_staging_db.sql` (branch first).

## Next steps
1. Push the branch (Claude GitHub App on the repo, or push the bundle) and open the PR; check CI.
2. Owner (free): Neon bootstrap on a branch; R2 buckets/tokens; Auth0 Free tenant + MFA check + 5 synthetic users;
   confirm the Vercel plan.
3. Decide A4/A6 (≈ $15.20/month on a $0 Hobby workspace; request in phase-1-7-integration.md). Then Render Blueprint → migrate job → platform admin → Vercel Production env vars → `live_checks.sh`.
4. With A9: `acceptance.mjs`, `scanner_checks.mjs OUTAGE=1`, backup + restore into a Neon branch.
