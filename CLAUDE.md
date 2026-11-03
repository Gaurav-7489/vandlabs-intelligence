# CLAUDE.md — working rules for VandLabs Intelligence

Read `docs/HANDOFF.md` first: it holds the current state, verified results, open approvals and the next milestone.

## Project in one paragraph
Enterprise organizational-intelligence platform. Multi-tenant FastAPI modular monolith (`services/api`, worker = `python -m app.worker`)
+ React/Vite/TS/Tailwind SPA (`apps/web`, served by a Cloudflare Worker that proxies `/api/*`). PostgreSQL (Neon in staging) with
FORCE row-level security, Redis (Render Key Value) for sessions/rate limits/worker wake-up, R2 for documents. First workflow:
upload → malware scan → sandboxed parse → risk insight → decision → approval by a different user → verified task → outcome → audit.

## Owner's standing instructions (do not relax)
- Never fabricate results. Report test/CI outcomes exactly; say what was NOT verified.
- Synthetic data only. No customer data in staging without explicit approval.
- Do **not** create paid resources, configure billing, merge PRs, or deploy to production without the owner's explicit approval.
  Approvals A1–A9 are listed in `docs/operations/staging-provisioning-checklist.md`.
- Do **not** reuse infrastructure of other VandLabs products (Automotive Intelligence / Automobile Engine / AVIENDO Neon projects,
  existing Cloudflare Workers and R2 buckets). VandLabs Intelligence gets dedicated resources.
- Never ask for API keys/secrets in chat and never commit them. Secrets go into provider dashboards / GitHub Actions secrets.
- Do not disable or weaken tests or security checks to get CI green; fix the cause.
- Do not rewrite shared git history.
- No Phase 2 work (knowledge graph, advanced agents) until staging is live and security-validated.

## Security invariants (tests enforce these)
- Runtime roles `vand_app` / `vand_worker` are non-owner, no BYPASSRLS. `vand_owner` is used only by migrations (deploy job).
  `vand_backup` is read-only BYPASSRLS for pg_dump only. Owner credentials must never be in the runtime environment.
- Every tenant table (incl. `users`) has RLS ENABLED + FORCED; tenant context via `set_config('app.org_id', …, true)`.
- Audit log is append-only. Approver ≠ requester. Task execution is idempotent and server-verified.
- Staging/production settings refuse dev auth, http origins, local storage, missing scanner, short origin secret.

## Commands
```bash
cd services/api && ruff check . && mypy app && pytest -q          # needs Postgres 17 + Redis 7 (see README)
cd apps/web && npm run typecheck && npm run lint && npm test && npm run build
bash scripts/backup_restore_drill.sh                               # PG_DOCKER_IMAGE=postgres:17 when local client differs
python scripts/export_openapi.py > docs/api/openapi.json           # after any API change (CI checks freshness)
python scripts/check_runtime_lock.py                               # runtime lock must match tested lock
```
