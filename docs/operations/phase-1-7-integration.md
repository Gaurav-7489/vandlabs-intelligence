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
| `pytest -q -rs` (Postgres 17 + Redis 7, migrations from scratch) | **151 passed**, 0 skipped (re-run on clean `94e496e`) |
| Web `typecheck`, `lint`, `vitest`, `build` (`VERCEL=1` embeds 4 MB) | clean; **87 passed**; build OK (re-run on clean `94e496e`) |
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

## A4 / A6 approval request (re-checked 2026-11-03)
Vendor sites are blocked from the build sandbox; figures below come from the vendors' own pages **as quoted in search
results** on 2026-11-03. Confirm on the linked pages before approving.

| Resource (all Render, region Singapore) | Plan | Price | Status of the figure | Expected staging cost |
|---|---|---|---|---|
| Workspace | Hobby | $0 + compute; up to 25 services, 1 member, 5 GB bandwidth/month ([plans by feature](https://render.com/docs/new-workspace-plans), [changelog](https://render.com/changelog/updated-plans-for-render-workspaces)) | **Confirmed by official doc**: background workers and private services are available from Starter on Hobby; no Pro workspace needed | $0 |
| `vand-api-staging` web service | Starter 512 MB | $7/month, prorated per second ([pricing](https://render.com/pricing)) | confirmed | $7.00 |
| `vand-worker-staging` background worker | Starter 512 MB | $7/month, prorated | confirmed | $7.00 |
| `vand-redis-staging` Key Value | Free 25 MB | $0 | confirmed | $0 |
| `vand-clamav-staging` private service | Pro 4 GB / 2 CPU | $85/month ≈ $0.116/h, prorated per second | price confirmed; ClamAV needs ≥ 3 GiB, 4 GiB advised ([ClamAV Docker docs](https://docs.clamav.net/manual/Installing/Docker.html)) — Standard 2 GB is too small | **estimate** ≈ $1.20 for ~10 h/month |
| Bandwidth | included 5 GB/month on Hobby | overage price not verified | estimate | ≈ $0 (synthetic tests) |
| Disks / storage | none (no persistent disks in `render.yaml`) | — | confirmed by config | $0 |
| **Total** | | | | **≈ $15.20/month** (fixed $14.00 + scanner hours) |

**Unresolved (owner to confirm in the Render dashboard before approving):** whether a *suspended* service accrues any
charge (no official statement found; third-party guidance implies it does not), and any minimum charge per service
start. Worst case if the scanner is forgotten in the running state: $85/month — mitigated by suspending after each
window and checking the Billing page weekly.

**Not part of A4/A6 (separate decisions):** Auth0 Essentials $35/month only if Free cannot enforce MFA — sources
conflict and several state MFA is not on Free ([Auth0 MFA docs: factors depend on plan](https://auth0.com/docs/secure/multi-factor-authentication/multi-factor-authentication-factors.md));
Vercel Pro if the project is on Hobby (Hobby is limited to non-commercial personal use per
[Vercel fair-use guidelines](https://vercel.com/docs/limits/fair-use-guidelines)).

### Exact request
> Approve A4 + A6: on a Render **Hobby** workspace in Singapore, create from `render.yaml` at the approved commit:
> `vand-api-staging` (web, Starter), `vand-worker-staging` (worker, Starter), `vand-redis-staging` (Key Value, Free),
> `vand-clamav-staging` (private service, Pro 4 GB, **suspended except during test windows**). Expected ≈ $15.20/month;
> hard ceiling if the scanner were left running ≈ $99/month.

- **Scanner schedule:** resume at the start of a test window → wait ~2 min (signatures) → test → suspend. Target ≤ 10 h/month.
- **Pending uploads while suspended:** accepted, stored, `scan_pending`, never indexed or marked clean; retried every
  30 min; released automatically within ~60 s of the scanner answering; dead-lettered (still unindexed) after 7 days.
- **Rollback:** see deployment.md — Render rollback per service, Vercel Instant Rollback / remove `VAND_API_ORIGIN`
  (gateway fails closed), schema via restore into a new Neon branch (no reliance on downgrade scripts). Deleting the four
  Render services stops all charges.

## A9 live acceptance plan (prepared; run only after A9 approval)
| # | Check | How | Expected |
|---|---|---|---|
| 1 | Boundary checks (also used as the post-deploy smoke test; non-destructive, no uploads of files) | `tests/staging/live_checks.sh` with `WEB_URL`, `API_URL`, `PREVIEW_URL`, `ORIGIN_AUTH_SECRET` in env | all PASS: gateway 200, direct origin 403 (with and without a guessed secret), traversal 404, 413 for 4.6 MB, preview 503, `/readyz` database/db_role/redis ok |
| 2 | 17-step journey (real Auth0, real ClamAV, R2, Neon) | `tests/staging/acceptance.mjs` `IDP=auth0 EXPECT_SCAN=clean` with the 5 synthetic users | ACCEPTANCE PASSED |
| 3 | Cross-tenant denial | step 14 of the journey + outsider user | 403 foreign org, 404 foreign id |
| 4 | Genuine MFA | sign in as owner with MFA → `/api/v1/me` shows `mfa: true`; owner signing in without completing MFA (factor not enrolled) → privileged pages `mfa_required`; inspect a real ID token (Auth0 logs) for `amr` | MFA only when actually performed; no Action that sets `amr` unconditionally |
| 5 | Upload boundaries + quarantine | SPA with a 4.2 MB file; `tests/staging/scanner_checks.mjs` (EICAR) | client refusal message; EICAR quarantined, not searchable |
| 6 | Prolonged scanner outage | `scanner_checks.mjs OUTAGE=1 OUTAGE_WAIT_S=3600`; suspend ClamAV for > 30 min, then resume | held `scan_pending`, unindexed; processed automatically after resume |
| 7 | Encrypted backup + restore | run *Backup staging*; restore into a **new Neon branch** with a temporary read token; drill checks + `scripts/verify_staging_db.sql` | counts match, RLS forced, all checks ok; branch and read token deleted afterwards |
| 8 | Preview isolation | open a Vercel preview of the PR; `PREVIEW_URL=… live_checks.sh` | 503 `gateway_unavailable` |

## Remaining blockers (only these)
1. **GitHub write access** for Claude: the Claude GitHub App is not installed for `Gaurav-7489/vandlabs-intelligence`
   (push 403 "not in this session's authorized repository set"; GitHub API also refused). Fix: install it at
   https://claude.ai/connect-github and start a session with the repo selected — or push the bundle yourself.
2. **Decisions:** A4 + A6 (≈ $15.20/month, request above); confirm the Vercel plan.
3. **Owner steps (free):** Neon bootstrap on a branch (first check the owner role's BYPASSRLS); R2 buckets/tokens;
   Auth0 Free tenant + real MFA test (likely not available on Free — then a decision on Essentials $35/month).
4. **A9** live acceptance after 1–3.
