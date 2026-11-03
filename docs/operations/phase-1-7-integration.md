# Phase 1.7 — cloud integration status (2026-11-03)

Scope: connect the existing Vercel frontend, Neon project, R2, Auth0, the Python API and the worker, without paid
services that have not been approved. This document separates **verified** from **prepared** work.

## What this session could and could not reach
| System | Access from the Claude session | Consequence |
|---|---|---|
| GitHub `Gaurav-7489/vandlabs-intelligence` | Read only (public clone). Push refused: the Claude GitHub App is not installed for this repo/account | Work is on local branch `feat/phase-1-7-cloud-integration`, delivered as a patch/bundle |
| Neon `shy-leaf-28061787` | None (no connector, no API key) | Not inspected; steps prepared in the checklist |
| Cloudflare (R2) | None | Buckets not checked or created |
| Vercel | None; the sandbox network policy also blocks `*.vercel.app` | Live site not inspected; config changed in Git only |
| Auth0 | None | Free-plan MFA entitlement unverified |
| Render | None (and A4 not approved) | No backend host |

Access that was verified in another tool (e.g. ChatGPT connectors) does not carry over to this session.

## Gap list (and what was done)
| # | Gap | Severity | Status |
|---|---|---|---|
| G1 | Vercel served nothing on `/api/*` ⇒ every API call from the deployed SPA 404s | Blocker | **Fixed in code**: Vercel Edge gateway (ADR 0007). Activates once `VAND_API_ORIGIN` + secret are set in Vercel |
| G2 | Origin auth secret had no injection point on Vercel (an open rewrite would require disabling origin protection) | High | **Fixed**: secret added server-side by the gateway; client-forged trust headers stripped (tests) |
| G3 | Upload limit 25 MB vs Vercel's 4.5 MB body limit ⇒ opaque platform 413s | Medium | **Fixed**: 4 MB in SPA (Vercel builds), API `VAND_MAX_UPLOAD_BYTES=4194304`, gateway JSON 413 |
| G4 | Gateway forwarded `Expect: 100-continue` ⇒ upstream fetch failure (502) on large bodies | Medium | **Fixed** (found by the local rehearsal), regression test |
| G5 | Worker ignored SIGTERM for up to 30 s while blocked in BLPOP (platforms SIGKILL at ~30 s) | Medium | **Fixed**: stop signal interrupts the wait; regression test fails on the old code |
| G6 | Preview deployments could proxy to staging with the staging secret | Medium | **Fixed**: gateway refuses unless `VERCEL_ENV=production` (or explicit opt-in); also set env vars for Production scope only |
| G7 | Docs/workflow still deployed a second frontend on a Cloudflare Worker | Low | **Fixed**: removed from `deploy-staging.yml`; A3 marked superseded |
| G8 | No backend host (API + worker) | Blocker | **Needs A4 approval** — see Hosting |
| G9 | No scanner host; staging refuses to start without one | Blocker | **Needs A6 approval** — see Malware scanning |
| G10 | Neon roles/migrations/RLS not applied on the real project | Blocker | Needs Neon access or the owner to run checklist step 2/6 |
| G11 | R2 buckets/tokens, Auth0 tenant | Blocker | Owner actions (checklist steps 3–4) |
| G12 | Vercel plan: Hobby is intended for non-commercial use | Business | Owner to confirm the plan/terms |

## Verified in this session (commands and results)
| Check | Command | Result |
|---|---|---|
| Backend lint/types | `ruff check . && mypy app` | clean; 58 files |
| Backend tests (real Postgres 17 + Redis 7, migrations from scratch) | `pytest -q -rs` | **145 passed**, 0 skipped |
| Web | `npm run typecheck && npm run lint && npm test && npm run build` | clean; **83 tests passed**; build OK (`VERCEL=1` build embeds the 4 MB limit) |
| OpenAPI contract | `python scripts/export_openapi.py \| diff docs/api/openapi.json -` | unchanged |
| Secrets scan | `detect-secrets-hook --baseline .secrets.baseline` (CI command) | clean |
| Real ClamAV | `ClamdScanner` vs `clamav/clamav:stable` (1.5.4, sigs 2026-11-01) | EICAR ⇒ `infected` (Eicar-Test-Signature); CSV ⇒ `clean`; port closed ⇒ `unavailable` |
| Gateway, defensive probes (local Vercel emulation) | curl | direct origin without/with guessed secret ⇒ **403**; via gateway ⇒ 200; `..` traversal and non-`/api/v1` ⇒ 404; foreign `Origin` POST ⇒ 401; 5.6 MB ⇒ JSON 413 |
| **17-step acceptance, real browser** | `tests/staging/run_local_rehearsal.sh` + `acceptance.mjs` (`IDP=test-issuer EXPECT_SCAN=clean`) | **PASSED** twice (before and after the gateway fixes): sign-in, org, upload, real clean scan, ingest, insight, decision, separate approver, verified execution, task, outcome, audit, cross-tenant 403/404, refresh/logout, responsive, no 5xx/console errors |
| Worker shutdown | SIGTERM on the idle rehearsal worker | exits in 1.6 s (was up to 30 s) |

Rehearsal ≠ live verification: it used a local OIDC test issuer, local storage, local Postgres/Redis and a local
Node emulation of Vercel routing/headers. Nothing above proves Auth0, R2, Neon or Vercel behaviour.

## Hosting (A4) — the exact blocker
The API (FastAPI, long requests up to the parser timeout) and the worker (long-running BLPOP loop, sandboxed parsers,
ClamAV calls) need two always-on processes in the same private network as Redis.
- **Vercel** cannot host them: functions are short-lived and the worker is a daemon.
- **Render Free** (render.com/docs/free): web services only — **no background workers**; spins down after 15 min
  without inbound traffic (~1 min cold start); may restart at any time; 750 instance-hours/month. A free combined
  API+worker process would need a code change (worker loop inside the API process), would stop processing when spun
  down, and would put parser memory in the request-serving process. Not recommended; not implemented.
- **Recommended:** approve **A4 = Render Starter API ($7/mo) + Starter worker ($7/mo), Singapore** as in `render.yaml`
  (Key Value Free, A5, is created with it). No other spending is implied.

## Malware scanning (A6)
No safe free option was found: ClamAV needs ≈ 1.2 GiB for signatures (~2× during reload); Render Free/Starter
(512 MB) cannot hold it, and exposing a scanner from a personal machine is not acceptable. The scanner requirement
stays on (staging/production refuse to start without it). **Recommended:** approve **A6 as "suspended by default,
resumed only for test windows"** — billed per second ≈ $0.12/h, i.e. ≈ $1–2/month for ~10 h of testing.

## Neon notes (A1, exists)
- Free plan: scale-to-zero is always on at 5 min and cannot be disabled (neon.com scale-to-zero guide). The API
  default for the suspend timeout is 300 s; `suspend_timeout_seconds: 0` in the create response should mean "plan
  default" — confirm the console shows 5 min (it is not documented as "never suspend").
- The worker touches Postgres only on a wake signal, a due retry, or the 30-min sweep; heartbeats go to Redis. Each
  sweep wakes compute for ~5 min ⇒ ≈ 48 × 5 min ≈ 4 h/day of 0.25 CU at idle ≈ 30 CU-h/month, under the 100 CU-h cap.
  Raise `VAND_WORKER_IDLE_SWEEP_SECONDS` (e.g. 3600) if usage approaches the cap.

## Approvals still needed (only these)
1. **A4** — Render Starter API + worker, ≈ $14/month.
2. **A6** — ClamAV private service, suspended by default, ≈ $0.12/h while running.
3. **A9** — live acceptance run, after 1–2 and the owner steps below.
4. **Only if Auth0 Free cannot require MFA** — Auth0 B2C Essentials, $35/month (a new approval; A7 covers Free only).

## Owner actions (no cost)
1. Grant Claude push access to the repo (https://claude.ai/connect-github → install the Claude GitHub App on the repo).
2. Neon: run checklist step 2 (roles with generated passwords) or give a session scoped access.
3. Cloudflare: create the two R2 buckets/tokens if missing (step 3). Auth0: Free tenant + MFA check (step 4).
4. Vercel: Production-scope env vars `VAND_API_ORIGIN`, `VAND_ORIGIN_AUTH_SECRET` once the API host exists (step 7);
   confirm the plan.
