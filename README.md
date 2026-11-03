# VandLabs Intelligence

Enterprise organizational-intelligence platform: it sits above a company's existing systems and turns scattered records into
**evidence → insight → decision → approved action → verified outcome**.

> **Status: Phase 1.7 — SPA live on Vercel (API gateway prepared), backend NOT hosted, staging NOT provisioned, NOT production-ready.** Current state and next steps: [docs/HANDOFF.md](docs/HANDOFF.md).
> See [docs/product/status.md](docs/product/status.md) for exactly what is implemented, tested, partial, or blocked.

## What works today (verified by tests in this repo)

Upload a commitments/tasks spreadsheet → background ingestion → deterministic risk rules → evidence-backed insight → decision →
approval by a *different* authorized person → idempotent, verified task creation → outcome journal → audit trail. Multi-tenant with
PostgreSQL Row-Level Security, server-side RBAC, MFA gating for privileged roles, distributed rate limiting, safe uploads.

## Repository layout

```
apps/web/            React + TypeScript + Vite + Tailwind client (client-side routing, code-split routes, TanStack Query)
services/api/        FastAPI modular monolith (+ worker entrypoint `python -m app.worker`)
infra/database/      Postgres role setup (owner / app / worker)
docs/                architecture, ADRs, security, operations, product status, OpenAPI export
tests/e2e/           Browser end-to-end test of the full workflow (Playwright)
scripts/seed_demo.py Seeds two SYNTHETIC demo organizations via the API
```

## Local setup

Prereqs: Python 3.12+, Node 22+, PostgreSQL 17, Redis 7.

```bash
# 1. Database roles + databases (once, as a Postgres superuser; local-dev passwords only)
psql -f infra/database/roles.sql && createdb -O vand_owner vand_dev

# 2. Backend
python -m venv .venv && . .venv/bin/activate
pip install -r services/api/requirements.lock.txt
cd services/api && alembic upgrade head
python -m app.cli create-platform-admin platform@vandlabs.example.com
uvicorn app.main:create_app --factory --port 8000     # API  (docs at /docs in non-production)
python -m app.worker                                  # worker (separate terminal)

# 3. Frontend
cd apps/web && npm ci && npm run dev                  # http://localhost:5173 (proxies /api -> :8000)

# 4. Optional synthetic demo data (needs API running; worker ingests it)
python scripts/seed_demo.py
```

Sign in locally as `manager@northwind-demo.example.com` (requester) and `approver@northwind-demo.example.com` (approver).
The local sign-in form exists only when `VAND_AUTH_MODE=dev`; the API refuses that mode in staging/production.

## Tests

```bash
cd services/api && pytest -q                 # 151 tests, real Postgres + Redis, migrations applied from scratch
cd services/api && ruff check . && mypy app
cd apps/web && npm run typecheck && npm run lint && npm test && npm run build
node tests/e2e/workflow.mjs                  # needs API + worker + web running and seeded demo data
PY=python bash tests/e2e/run_oidc_stack.sh && node tests/e2e/auth.mjs   # real OIDC browser flow (see docs)
```

## Docs

[Architecture](docs/architecture/overview.md) · [ADRs](docs/decisions) · [Threat model & control status](docs/security/threat-model.md) ·
[Deployment](docs/operations/deployment.md) · [Product status & limitations](docs/product/status.md) · [OpenAPI](docs/api/openapi.json)
