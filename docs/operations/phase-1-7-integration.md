# Phase 1.7 — staging integration status (updated 2026-11-03)

Current state below includes direct GitHub, Vercel, Neon and Cloudflare checks performed on 2026-11-03. Historical local results remain labelled separately.

## Resource state (approved → provisioned → configured → deployed → verified)
| Item | Approved | Provisioned | Configured / deployed | Verified / remaining blocker |
|---|---|---|---|---|
| GitHub Phase 1.7 | yes | PR #14 merged | PR #15 runtime fix merged; main includes `112aee5` | API, web, secrets and e2e passed for both PRs; original file-tree integrity recorded in #14 |
| A1 Neon `shy-leaf-28061787` | yes, reuse | verified existing Free project, PG 17 / Singapore | `vand_staging`, four SQL-created roles, revisions 0001–0004 applied on an isolated branch and then main | 28/28 verification rows pass on main; 16 tenant tables force RLS; runtime app role has no bypass/schema-create privileges |
| A2 R2 documents/backups | yes, free allowance | both APAC buckets created | r2.dev disabled; no custom domains | private configuration verified; scoped credentials and object/backup operations pending deployment secret stores |
| A3 Cloudflare frontend | removed | — | do not deploy | Vercel remains the frontend host |
| A4 API + worker | pending paid decision | not created | `render.yaml` prepared | Render connection unavailable in this chat |
| A5 Key Value | approved with A4 | not created | prepared | dependent on Render |
| A6 ClamAV | pending paid decision | not created | prepared | dependent on Render and A6 approval |
| A7 Auth0 | Free only | not checked | not configured | account access and genuine MFA verification required |
| A8 AI | disabled | — | no provider keys | remains disabled |
| A9 live acceptance | pending | — | plan/scripts ready | full live journey not run |
| Vercel gateway | existing project | deployed on main | production deployment `dpl_3dqEZFyuZsUVjYZEYWJUJjvVdAc1` READY | homepage 200; auth/config JSON 503 while unconfigured. No gateway env vars exist; API origin/secret remain pending |

## Production runtime correction
The first merged gateway crashed with `ERR_MODULE_NOT_FOUND`: Node ESM could not resolve the extensionless `../src/edge/proxy` import. PR #15 changes it to `../src/edge/proxy.js`. A regression test transpiles the gateway/helper and loads them in a separate Node ESM process; it fails before the correction and passes after it. All 88 frontend tests, lint/types/build and GitHub's API/web/secrets/e2e checks passed. The deployed route now returns the intended fail-closed JSON 503 instead of a function crash.

## Database provisioning evidence
The project owner passed the CREATEROLE/CREATEDB/BYPASSRLS preflight. Roles were created with SQL, as required by `neon_bootstrap.sql`; API-created roles inherit `neon_superuser` and are unsuitable for runtime use. Upgrade statements from committed Alembic revisions 0001–0004 were applied transactionally as `vand_owner` and the revision recorded as `0004`. The read-only verification script passed 28/28 rows on both the isolated validation branch and main. Authenticated queries as `vand_app` show no bypass privilege, no schema-create privilege and zero visible users/documents without tenant context. This is database setup/security verification, not the A9 application acceptance journey. Connection-string secrets remain outside the repository and logs.

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

## Historical local verification on code-bearing candidate 94e496e (2026-11-03)
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

**Still unverified:** Auth0 entitlement/real MFA; runtime traffic through the Neon pooler; R2 object/backup operations; Render build/private networking/scanner; Vercel configured upstream forwarding, trusted client-IP behaviour and account plan. Neon owner/roles/schema and Vercel gateway startup are verified above.

## A4 / A6 approval request (re-checked 2026-11-03)
The original cost request was researched from the Claude sandbox. Current official [Render pricing](https://render.com/pricing), [billing FAQ](https://render.com/docs/faq), and [service billing explanation](https://render.com/articles/how-much-does-cloud-application-hosting-cost-for-small-businesses) support the compute rates and active-second billing below. No Render resources have been created; confirm account allowances and spend controls before purchase.

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

**Cost limits:** official Render guidance bills paid compute for active seconds, and paid services run continuously until suspended. The test-window estimate assumes suspension outside those windows and no persistent disks. Confirm the account's minimums, bandwidth/build allowances and spending controls before approval. Leaving the scanner running adds about $85/month in compute; the roughly $99 combined compute scenario is not a spending cap and excludes overages.

**Not part of A4/A6 (separate decisions):** Auth0 Essentials $35/month only if Free cannot enforce MFA — sources
conflict and several state MFA is not on Free ([Auth0 MFA docs: factors depend on plan](https://auth0.com/docs/secure/multi-factor-authentication/multi-factor-authentication-factors.md));
Vercel Pro if the project is on Hobby (Hobby is limited to non-commercial personal use per
[Vercel fair-use guidelines](https://vercel.com/docs/limits/fair-use-guidelines)).

### Exact request
> Approve A4 + A6: on a Render **Hobby** workspace in Singapore, create from `render.yaml` at the approved commit:
> `vand-api-staging` (web, Starter), `vand-worker-staging` (worker, Starter), `vand-redis-staging` (Key Value, Free),
> `vand-clamav-staging` (private service, Pro 4 GB, **suspended except during test windows**). Expected ≈ $15.20/month;
> continuous-scanner compute estimate ≈ $99/month, excluding overages; this is not a budget cap.

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

## Remaining blockers
1. **Render connection and A4/A6 decision:** the Render integration is available but not installed/connected here. Paid resources remain unapproved and uncreated.
2. **Auth0:** account access, Free tenant/application setup and genuine MFA test. Do not buy a plan or weaken the MFA requirement automatically.
3. **Deployment secrets:** once the backend/secret stores are available, create scoped R2 credentials, configure API/worker/workflow secrets, confirm the intended initial platform-admin identity, and add Vercel Production-only gateway origin/secret values.
4. **Vercel plan:** the connected project/team summaries did not expose the billing plan; verify it in account billing before commercial use.
5. **A9:** live acceptance, scanner EICAR/outage/resume and backup restore remain pending.

GitHub publication, main merges, Neon schema/role setup and private R2 bucket creation are complete. Validation branches remain available as setup evidence; no existing database or bucket data was deleted.
