# Product status (Phase 1.7, 2026-11-03; frontend on Vercel, backend NOT hosted, staging NOT provisioned)

Legend: **V** implemented and verified (automated test or measured) · **E** implemented, not externally verified · **P** partial · **N** not implemented · **B** blocked by credentials/account.

| Area | Status | Evidence / caveat |
|---|---|---|
| Tenant isolation (RLS FORCE incl. `users`, non-owner roles), RBAC, audit append-only | V | 138 backend tests incl. raw-SQL cross-tenant and privileged-role tests (0 skipped) |
| Unsafe DB role detection (superuser / BYPASSRLS / **membership in neon_superuser or any privileged role** / owner / RLS not forced) | V | fatal at startup in staging/production; `/readyz` `db_role`; tested with owner and BYPASSRLS roles |
| OIDC Authorization Code + PKCE, BFF encrypted sessions, CSRF, revocation, MFA gate | V against a **local test issuer** (24 tests + real-browser E2E) ; **B** against Auth0 | see docs/operations/auth0-setup.md |
| Session restore on refresh, expiry handling, sign-out cache wipe | V | browser E2E |
| Rate limits (per user/IP/org), atomic across replicas, concurrency cap for AI, bounded job queue | V | concurrency tests with 4 limiter instances; limits untuned (no capacity claim) |
| Worker reliability: two workers, crash recovery, retries, dead-letter, scanner-hold, prompt SIGTERM | V | tests; Phase 1.7 fixed SIGTERM waiting up to 30 s inside BLPOP (now ≈ 1–2 s; regression test) |
| Upload validation + **sandboxed parser** (rlimits, timeout, netns when available, socket block) | V | memory/timeout/network tests. `unshare` isolation depends on host kernel; not a seccomp/container sandbox |
| Malware scanning (clamd INSTREAM client, hold-until-scanned, quarantine, truthful statuses) | V against **real ClamAV 1.5.4** (local container): EICAR ⇒ quarantined + unsearchable, clean ⇒ clean, scanner down ⇒ held `scan_pending` (never clean), **holds survive long outages and are released automatically when clamd answers** (real stop/start); **B** hosted ClamAV (A6) | `scan_status` never claims clean without a scanner OK |
| PDF / DOCX / XLSX / CSV / TXT parsing with provenance | V on programmatically generated real files | no scanned/OCR support (N); no very large real-world corpus tested |
| Object storage | V LocalStorage + S3 protocol vs moto emulator; tenant-prefix guard; **B** real R2 | no signed URLs issued (files are never directly downloadable) |
| AI adapters (Anthropic/OpenAI): request/response schema, timeout/429/5xx failover, token accounting | V with `httpx.MockTransport`; **B** live APIs | no live call was made; grounding tested with a fake provider |
| AI pricing | V explicit dated config; USD `null` when unconfigured | no prices are built in |
| Streaming answers | N | single-response only |
| Explanation history (versioned, canonical insight untouched) | V | |
| Decisions/approvals/verified execution; direct low-risk tasks labelled and audited | V | docs/security/action-risk-matrix.md |
| Frontend: perf, a11y basics, CSP | V: strict CSP (no inline scripts) 0 violations in browser; contrast tests; responsive overflow checks 320–1440 | no screen-reader audit, no Lighthouse/CWV, no list virtualization (cursor pages of 20 instead) |
| Same-origin API gateway on Vercel (`apps/web/api/gateway.ts`, Node.js runtime, ADR 0007) | V 29 unit tests + full acceptance run through the same code in a local Vercel emulation; **B** on Vercel (no API host yet) | uploads capped at 4 MB (Vercel 4.5 MB body limit). Cloudflare Worker kept, not deployed |
| Render blueprint, Dockerfile (runtime-only lock), deploy/backup workflows | Image **V built and run locally** (non-root, fail-closed staging config, health/readiness, < 1 s shutdown); blueprint **E**; **not deployed** | sandbox build needed a proxy-CA-only Dockerfile copy |
| Neon/R2 driver compatibility | V URL translation + pooler-mode queries; R2 checksum config | live services not reached |
| Supply chain | V runtime lock drift check, pip-audit (tested + runtime), CycloneDX SBOMs, Dependabot | actions not SHA-pinned; no hash pinning |
| CI (api, web, secrets, e2e) | V on GitHub | see PR #1 checks |
| Cloudflare WAF/Turnstile/rate-limit rules, origin restriction | B (dashboard) | shared-secret origin auth implemented and tested |
| Backups | V (drill in CI: dump as read-only BYPASSRLS role → restore → verify counts/RLS/isolation); **B** staging schedule | docs/operations/backups.md |
| Monitoring | V metrics endpoint + counters + queue snapshot; **N** alert delivery/tracing | docs/operations/observability.md |
| Staging acceptance test (17 steps) | V as **local rehearsal** through the gateway with real ClamAV (`tests/staging/run_local_rehearsal.sh`; test issuer); **B** live (A4, A6, A9) | tests/staging/acceptance.mjs |
| Connectors, knowledge graph, pgvector/hybrid search, OCR, agents | N | pgvector path documented only |

## Known limitations
Insight rules need a `depends on` column; ISO dates only; requester ≠ approver always; parser isolation is best-effort without containers; IdP outage preserves existing sessions; dev-mode sign-in exists only when `VAND_AUTH_MODE=dev`.
