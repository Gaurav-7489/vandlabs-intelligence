# Architecture overview

One modular monolith (FastAPI) + one worker process sharing a codebase, backed by PostgreSQL and Redis; a React SPA in front.
Split out services only when scale, isolation, or operations demand it (ADR-0001).

```
Browser (SPA) ──► Cloudflare ──► API replicas (stateless) ──► PostgreSQL (RLS)   ◄── Worker(s)
                                   │  ├─ Redis (shared rate-limit counters)           (claims jobs with SKIP LOCKED)
                                   │  ├─ Object storage (local dev / R2)
                                   │  └─ AI gateway (optional providers)
```

## Request path and tenancy
1. `get_identity` verifies the bearer token (OIDC JWKS in prod; HS256 dev token locally), binds/creates the user, applies per-user limits.
2. `get_principal` validates the *requested* `X-Org-ID` against the `memberships` table, enforces MFA for owner/admin, then opens a
   transaction with `set_config('app.org_id', …, true)`. **Role and permissions come only from the database.**
3. Handlers call `require(P.…)`. Every query then runs under PostgreSQL RLS (`FORCE ROW LEVEL SECURITY`), connecting as a non-owner role,
   so a missing `WHERE org_id` in application code still cannot leak another tenant's rows.
4. Platform admins have a separate scope that can touch only `organizations`/`users`; content tables have **no** platform policy.

## Modules (`services/api/app`)
`identity` (tokens, principals, RBAC, members, platform provisioning) · `documents` (upload API) · `ingestion` (validate, parse, extract, pipeline) ·
`search` (Postgres full-text) · `intelligence` (rules, analysis, insights, grounded explain/ask) · `decisions` (state machine, approvals, execution, outcomes) ·
`tasks` · `audit` · `ai` (provider-independent gateway) · `jobs` (durable queue) · `core` (config, db, errors, logging, rate limit, storage, pagination).

## Data flow of the first workflow
Upload → validate (extension, magic bytes, zip-bomb guard) → object storage (server-generated key) → `jobs` row (same transaction) →
worker parses, replaces derived chunks/records idempotently, stamps provenance (`document_id`, `Sheet!row N`) → `analyze` job runs pure
rule functions (`intelligence/rules.py`) → insights upserted by fingerprint (re-runs never duplicate; cleared conditions auto-resolve) →
human creates a decision → submit → a **different** user with `decisions.approve` approves → `execute` runs the single supported action
(`create_task`) under an idempotency key and verifies by re-reading the record → outcome recorded → closed. Every step is audited.

## Frontend
Persistent shell; each route is a lazy chunk; each dashboard widget owns its query (own skeleton, own error + retry); lists use keyset
cursors with IntersectionObserver; document status polls only while something is processing; all query keys include the org id and the cache
is cleared on org switch/sign-out. The access token is held in memory only.
