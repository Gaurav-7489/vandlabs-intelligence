# Phase 1.7 — staging integration status (updated 2026-11-03)

Only facts observed from the Claude sessions are marked verified. Nothing has been provisioned, configured or deployed
from these sessions: no Neon, Cloudflare, Vercel, Auth0 or Render access was available (no connectors; the sandbox
network also blocks `*.vercel.app`, `vercel.com`, `render.com`, `auth0.com`). GitHub access was read-only (clone);
push and the GitHub API were refused for this repository.

## Resource state (approved → provisioned → configured → deployed → live-verified)
| Item | Approved | Provisioned | Configured | Deployed | Live-verified | Next / blocker |
|---|---|---|---|---|---|---|
| A1 Neon `shy-leaf-28061787` (PG 17, Singapore) | ✅ reuse | ✅ (owner-reported; not seen by Claude) | ❌ roles/DB | ❌ migrations | ❌ | Owner: branch-first `infra/database/neon_bootstrap.sql` → migrate → `scripts/verify_staging_db.sql`. **Check that the owner role can create a BYPASSRLS role** |
| A2 R2 `vand-intel-staging-docs`, `vand-intel-staging-backups` | ✅ free tier | unknown | ❌ | — | ❌ | Owner: list buckets, create missing ones private, 2 scoped tokens |
| A3 Cloudflare frontend Worker | not required | — | — | — | — | Superseded by the Vercel gateway (ADR 0007) |
| A4 Render API + worker (Starter) | ❌ awaiting | ❌ | prepared (`render.yaml`) | ❌ | ❌ | **Decision needed** (cost below) |
| A5 Render Key Value Free | ✅ (with A4) | ❌ | prepared | ❌ | ❌ | Created with the A4 Blueprint |
| A6 ClamAV private service (Pro 4 GB) | ❌ awaiting | ❌ | prepared | ❌ | ❌ | **Decision needed** (cost below) |
| A7 Auth0 (Free only) | ✅ Free | unknown | ❌ | — | ❌ | Owner: confirm Free offers OTP/WebAuthn with policy *Always*; MFA availability depends on plan per Auth0 docs |
| A8 AI providers | ✅ disabled | — | disabled (no keys) | — | n/a | — |
| A9 Live acceptance | ❌ awaiting | — | scripts ready | — | ❌ | After A4/A6 + owner steps |
| Vercel project `vandlabs-intelligence` | existing | ✅ (live SPA) | gateway code ready; env vars ❌ | SPA only; gateway not deployed (branch unmerged) | ❌ | Merge PR (owner), set Production-only env vars after the API exists; **confirm plan** |

## Work in this phase (branch `feat/phase-1-7-cloud-integration`)
| Change | Why | Evidence |
|---|---|---|
| Vercel Function gateway `/api/v1/*` (Node.js runtime) adds the origin secret server-side; fails closed when unconfigured/preview; strips forged trust headers and `Expect`; safe paths only; bounded body (4,500,000 B) with JSON 413; cookies/redirects pass through | Without it the deployed SPA cannot reach any API | 29 unit tests; acceptance + live checks through the same code locally |
| Moved gateway from Edge to Node.js runtime | Edge Functions deprecated; Edge request body max 4 MB < 4 MiB upload + framing | 4 MiB multipart test: ≈ 4.19 MB on the wire, ~300 KB headroom |
| Upload limit 4 MiB (SPA on Vercel builds, API `VAND_MAX_UPLOAD_BYTES`) | Vercel 4.5 MB body limit | build output, tests |
| Worker: SIGTERM interrupts the BLPOP wait | Was up to 30 s ⇒ platform SIGKILL | regression test; container stop 0.48 s |
| **Scanner holds no longer dead-letter in ~2 min**; worker PINGs clamd (no DB) and releases holds automatically; holds retry every 30 min, expire after 7 days | A6 plan keeps ClamAV suspended between test windows; uploads would have been stuck until manual reprocess | 3 new tests; real ClamAV stop/start: held 08:51:52 → resumed 08:53:52 → released + clean 08:54:22 |
| DB safety check also refuses **membership** in `neon_superuser`/superuser/BYPASSRLS/`pg_*_all_data` roles | Neon console roles are `neon_superuser` members (SET ROLE path around RLS) | tests fail on old code, pass now |
| `infra/database/neon_bootstrap.sql` (atomic roles, `vand_staging` owned by `vand_owner`, no secrets in file) + `scripts/verify_staging_db.sql` | Neon-safe role setup + read-only verification | run as a NON-superuser CREATEROLE/CREATEDB role on PG 17: bootstrap → migrations → all checks ok; without BYPASSRLS on the creator it fails atomically (0 roles left) |
| Staging `VAND_PARSER_MEMORY_MB=256` | Starter has 512 MB; 1024 MB sandbox budget could OOM the container | 4.7 MB CSV and 49k-row XLSX parse at 192/256 MB; peak child RSS ≈ 255 MB |
| `auth0-setup.md`: MFA Action derives `amr` only from `event.authentication.methods` | The previous wording ("set amr if missing") would fake MFA | doc review |
| `tests/staging/live_checks.sh`, `tests/staging/scanner_checks.mjs` | Prepared live boundary + EICAR/outage checks for A9 | pass against the local rehearsal stack |
| deploy-staging workflow: no Cloudflare frontend; smoke test checks gateway 200 + direct-origin 403 | A3 superseded | YAML validated |
| CLAUDE.md / HANDOFF.md (recovered from branch `claude/peaceful-mendel-j30y5u`) updated to the Vercel topology | Session continuity | — |

## Fresh verification on the candidate commit (local, 2026-11-03)
| Check | Result |
|---|---|
| `ruff check . && mypy app` | clean (58 files) |
| `pytest -q -rs` (Postgres 17 + Redis 7, migrations from scratch) | **151 passed**, 0 skipped |
| Web `typecheck`, `lint`, `vitest`, `build` (`VERCEL=1` embeds 4 MB) | clean; **87 passed**; build OK |
| OpenAPI contract export | unchanged |
| Runtime lock check | 52 pins match the tested lock |
| detect-secrets (CI command) | clean |
| Backup/restore drill (PG 17 client/server) | PASSED: identical counts, RLS forced, 23 policies, app role isolated on restore |
| Production Docker image (`services/api/Dockerfile`) | builds\*; runs as `vand`; `unshare` present; staging with no config **refuses to start** (exit 1); `/healthz` ok; `/readyz` database/db_role/redis ok; no secret ⇒ 403; API and worker stop in < 1 s |
| 17-step acceptance (real browser, gateway code, real ClamAV, test OIDC issuer) | **PASSED** |
| `live_checks.sh` vs local stack | 14/14 applicable PASS (preview check skipped: needs a real preview URL) |
| `scanner_checks.mjs OUTAGE=1` with real ClamAV stop/start | **PASSED** (EICAR quarantined + unsearchable; held while down; auto-processed after resume) |

\* The sandbox blocks network access from inside `docker build`; the image was built from an unmodified copy of the
context with a throwaway Dockerfile that only adds the sandbox proxy CA/proxy settings. Render builds the committed
Dockerfile directly (not verified on Render).

**Not verified:** Auth0 (MFA entitlement, real `amr`), Neon (owner-role BYPASSRLS ability, pooler), R2, Render (build,
private networking, suspension billing), Vercel (function runtime, `x-real-ip`, env scoping, plan).

## A4 / A6 approval request (prices from Render's pricing page and changelog as quoted in search results on
2026-11-03; render.com itself was unreachable from the sandbox — confirm on the page before approving)
| Resource | Plan | Price | Expected staging use | Expected cost |
|---|---|---|---|---|
| Render workspace | Hobby | $0 (Pro is $25/month flat since 1 Aug 2026) | — | $0 — **confirm Hobby allows paid private services**; if Pro is required, +$25 |
| `vand-api-staging` web service | Starter 512 MB / 0.5 CPU | $7/month, prorated per second | always on | $7.00 |
| `vand-worker-staging` background worker | Starter | $7/month, prorated | always on | $7.00 |
| `vand-redis-staging` Key Value | Free (25 MB, no persistence) | $0 | always on | $0 |
| `vand-clamav-staging` private service | Pro 4 GB / 2 CPU (ClamAV: min 3 GiB, configure 4 GiB) | $85/month ≈ **$0.116/h** prorated | suspended; ~10 h of test windows/month | ≈ $1.20 (≈ $85 if left running) |
| Bandwidth | Hobby includes 5 GB/month (third-party report) | overage not verified | synthetic tests | ≈ $0 |
| **Total** | | | | **≈ $15.20/month** (+$25 if Pro workspace is required; +$35 Auth0 Essentials only if Free lacks MFA — separate decision) |

Not verified: whether a **suspended** service accrues charges (forum staff say charges accrue while provisioned;
the docs page could not be read). Scanner schedule: resume before a test window (Render → service → Resume), wait
~2 min for signatures, test, then Suspend. While suspended uploads wait unindexed in `scan_pending` and are processed
automatically on resume (see deployment.md).

## Remaining blockers (only these)
1. **GitHub write access** for Claude (Claude GitHub App on this repo) — or push the bundle yourself.
2. **Decisions:** A4 (+A6) at the cost above; confirm the Vercel plan (Hobby is restricted to non-commercial personal
   use per Vercel's fair-use guidelines — VandLabs is a company; Pro would be a separate decision).
3. **Owner steps (free):** Neon bootstrap on a branch; R2 buckets/tokens; Auth0 Free tenant + MFA check + 5 synthetic users.
4. **A9** live acceptance after 1–3.
