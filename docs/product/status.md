# Product status (after Phase 1.5)

Legend: **V** implemented and verified (automated test or measured) · **E** implemented, not externally verified · **P** partial · **N** not implemented · **B** blocked by credentials/account.

| Area | Status | Evidence / caveat |
|---|---|---|
| Tenant isolation (RLS FORCE, non-owner roles), RBAC, audit append-only | V | 112 backend tests incl. raw-SQL cross-tenant tests |
| Unsafe DB role detection (superuser / BYPASSRLS / owner / RLS not forced) | V | fatal at startup in staging/production; `/readyz` `db_role`; tested with owner and BYPASSRLS roles |
| OIDC Authorization Code + PKCE, BFF encrypted sessions, CSRF, revocation, MFA gate | V against a **local test issuer** (24 tests + real-browser E2E) ; **B** against Auth0 | see docs/operations/auth0-setup.md |
| Session restore on refresh, expiry handling, sign-out cache wipe | V | browser E2E |
| Rate limits (per user/IP/org), atomic across replicas, concurrency cap for AI, bounded job queue | V | concurrency tests with 4 limiter instances; limits untuned (no capacity claim) |
| Worker reliability: two workers, crash recovery, retries, dead-letter, scanner-hold | V | tests |
| Upload validation + **sandboxed parser** (rlimits, timeout, netns when available, socket block) | V | memory/timeout/network tests. `unshare` isolation depends on host kernel; not a seccomp/container sandbox |
| Malware scanning (clamd INSTREAM client, hold-until-scanned, quarantine, truthful statuses) | V protocol with a fake clamd; **B** against real ClamAV | no ClamAV available here; `scan_status` never claims clean without a scanner OK |
| PDF / DOCX / XLSX / CSV / TXT parsing with provenance | V on programmatically generated real files | no scanned/OCR support (N); no very large real-world corpus tested |
| Object storage | V LocalStorage + S3 protocol vs moto emulator; tenant-prefix guard; **B** real R2 | no signed URLs issued (files are never directly downloadable) |
| AI adapters (Anthropic/OpenAI): request/response schema, timeout/429/5xx failover, token accounting | V with `httpx.MockTransport`; **B** live APIs | no live call was made; grounding tested with a fake provider |
| AI pricing | V explicit dated config; USD `null` when unconfigured | no prices are built in |
| Streaming answers | N | single-response only |
| Explanation history (versioned, canonical insight untouched) | V | |
| Decisions/approvals/verified execution; direct low-risk tasks labelled and audited | V | docs/security/action-risk-matrix.md |
| Frontend: perf, a11y basics, CSP | V: strict CSP (no inline scripts) 0 violations in browser; contrast tests; responsive overflow checks 320–1440 | no screen-reader audit, no Lighthouse/CWV, no list virtualization (cursor pages of 20 instead) |
| Edge Worker, `_headers`, wrangler, Render blueprint, Dockerfile, compose, CI/deploy workflows | **E** | written, **not built/deployed**; no Docker daemon here; CI not yet seen green on GitHub (see PR) |
| Cloudflare WAF/Turnstile/rate-limit rules, origin restriction | B (dashboard) | shared-secret origin auth implemented and tested |
| Backups/DR, monitoring/alerting/tracing | N | |
| Connectors, knowledge graph, pgvector/hybrid search, OCR, agents | N | pgvector path documented only |

## Known limitations
Insight rules need a `depends on` column; ISO dates only; requester ≠ approver always; parser isolation is best-effort without containers; IdP outage preserves existing sessions; dev-mode sign-in exists only when `VAND_AUTH_MODE=dev`.
