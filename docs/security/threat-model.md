# Threat model & control status

Scope: the code in this repository, evaluated locally. **Nothing here has had an external penetration test.** "Tested" means an automated test in this repo
exercises it against real Postgres/Redis. Infrastructure controls (Cloudflare WAF, Turnstile, secrets manager, backups) are *not configured* and are listed as such.

## Assets & actors
Tenant documents/records/decisions/audit; credentials (DB, storage, AI keys); user sessions. Actors: anonymous internet, authenticated user of tenant A, malicious/compromised
member, VandLabs platform admin, malicious uploaded file, prompt-injecting document, compromised AI provider response.

## Control matrix
| Threat | Control | Status |
|---|---|---|
| Cross-tenant read/write (BOLA/IDOR) | Membership check + RLS FORCE + non-owner role; 404 for foreign ids; identical 403 for unknown vs foreign org | **Implemented & tested** (API + raw-SQL tests) |
| Platform admin snooping on customers | Separate scope with no policy on content tables | **Implemented & tested** |
| Privilege escalation / forged roles | Roles only from DB; admin cannot grant owner/admin; last-owner protection | **Implemented & tested** |
| Missing MFA for privileged roles | `amr` claim required for owner/admin/platform admin | **Implemented & tested** (depends on IdP supplying `amr`) |
| Unverified-email account takeover on invite | Invited identity binds only with `email_verified=true`; no identity merging | **Implemented & tested** |
| Approval bypass / self-approval | Server-side state machine, `decisions.approve`, requester ≠ approver | **Implemented & tested** |
| Duplicate execution / replay | Idempotency key + unique constraint; verification by re-read | **Implemented & tested** |
| Audit tampering | Append-only (trigger + revoked UPDATE/DELETE/TRUNCATE) | **Implemented & tested** |
| Brute force / API abuse | Redis token bucket per user/IP/policy, 429 + Retry-After, fail-closed on expensive policies | **Implemented & tested** (limits are starting values; not load-tested) |
| Malware / hostile parser input | clamd scan gate (fail-closed, hold until scanned), quarantine, sandboxed parser (rlimits/timeout/netns) | **Implemented & tested** (fake clamd, real limit tests); real ClamAV **blocked** |
| Malicious uploads | Extension allowlist, magic bytes, zip-expansion & member caps, macro rejection, size cap, sanitized names, server-generated keys, bounded parsing, formulas never evaluated | **Implemented & tested**; **no AV/malware scanning**; parsing has row/char caps but no hard process-level CPU/time sandbox |
| SQL injection | Parameterized SQLAlchemy; `websearch_to_tsquery` for user search | **Implemented & tested** (spot test) |
| Prompt injection / ungrounded AI | Evidence-only prompts, untrusted-data framing, strict JSON, citation ⊆ provided evidence else rejected, "insufficient evidence" path, no tools exposed to model | **Implemented & tested with a fake provider**; **not evaluated against real models** |
| AI cost abuse | Per-user AI rate limit, bounded input/output, per-org daily token budget enforced before provider call | **Implemented & tested** |
| Secrets in repo/logs | `.env` ignored, detect-secrets baseline in CI, log redaction, prod config guards | **Implemented & tested** (guards, redaction); CI job **unverified until first run** |
| XSS / clickjacking / MIME sniffing (API) | JSON-only API with restrictive CSP, nosniff, DENY framing, no-store | **Implemented & tested** (headers); SPA CSP **not yet set** (set at Cloudflare/host) |
| Token theft from browser storage | BFF: opaque HttpOnly SameSite=Lax session cookie, no tokens in JS (browser-verified); refresh token encrypted at rest in Redis | **Implemented & tested** against a test issuer; not against Auth0 |
| CSRF | Cookie sessions: Origin allowlist + per-session CSRF token on all unsafe methods (CORS is not relied on) | **Implemented & tested** |
| SSRF | No server-side fetch of user-supplied URLs exists yet | **N/A today**; required before connectors ship |
| Edge: WAF/DDoS/bot/Turnstile | — | **Not configured** (needs Cloudflare account/zone) |
| Secrets management / rotation | — | **Not configured** (needs hosting decision) |
| Backups / restore testing / DR | — | **Not configured** (see operations doc) |
| Data deletion/retention/export | Document deletion propagates to chunks, records, insights (tested). Retention policy, export, tenant offboarding | **Partial / not implemented** |
| RLS bypass by misconfiguration | Startup (staging/prod) + `/readyz` check: not superuser, no BYPASSRLS, owns no tenant tables, RLS forced | **Implemented & tested**; must also be run against Neon |
| Bypassing the edge to hit the origin | `X-Origin-Auth` shared secret; `CF-Connecting-IP` only trusted when it validates | **Implemented & tested**; WAF/DDoS rules **not configured** |

## Release blockers before real customer data
1. Run the Auth0 checklist in staging (MFA `amr` claim, revocation latency, invitation flow).
2. Stand up staging with Cloudflare, Neon, R2, secrets manager; run migrations as `vand_owner`, app as `vand_app`; verify RLS in that environment.
3. Run real ClamAV in staging; consider container/seccomp isolation for the parser.
4. Independent security review / penetration test; load test to set real rate-limit values.
5. Backups + restore drill; incident runbook ownership.
