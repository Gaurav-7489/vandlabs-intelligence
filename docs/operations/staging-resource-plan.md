# Staging resource plan (NOTHING below is provisioned; no billing has been enabled)

Prices were read from vendor documentation on 2026-11-03 via web search; **re-verify on the live pricing pages before purchasing** (several results were snapshots of unknown age, and Neon's/Auth0's own pages conflict with older posts).

## Existing accounts (inspected read-only)
The connected Neon org (`Gaurav`, **free plan**) holds 3 projects and the Cloudflare account holds 12 Workers + 8 R2 buckets, **all belonging to other VandLabs products** (Automobile Engine / AVIENDO / dealer-AI / platform). They are not used, modified or deployed into. VandLabs Intelligence gets its **own** Neon project, R2 bucket and Worker so blast radius, credentials and backups stay separate. Creating them still needs your approval.

## Plan (lowest cost that can validate staging)
| Service | Role | Cheapest option | Recurring cost (verified) | Limitations / notes | Permissions needed |
|---|---|---|---|---|---|
| Cloudflare Workers + static assets | SPA + `/api/*` proxy | Free plan | $0 (100k Worker requests/day; static asset requests free per docs; paid plan is $5/mo min if the account is already on it) | Free: 10 ms CPU/invocation — proxy is light but watch uploads; 1 Worker request per API call | Workers deploy token (scoped), account id |
| Cloudflare R2 | Private documents | Free tier | $0 within 10 GB-mo, 1M Class A, 10M Class B per month; then $0.015/GB-mo, $4.50/M Class A, $0.36/M Class B; egress free | Private bucket + scoped token; no public domain | R2 bucket create + Object RW token |
| Neon Postgres | Core DB (RLS) | **New project** on Free plan | $0 (docs: 100 CU-h/project, 1 GB/project, scale-to-zero after 5 min, 5 GB egress; no overage billing, compute suspends at limit). Launch plan if needed: $0.106/CU-h + $0.35/GB-mo | Cold starts after idle; only ~6 h history retention on Free ⇒ **not a real backup** (see backups); pgvector available later | Create project, create roles via SQL |
| Render API web service | FastAPI | Starter | $7/mo (0.5 CPU, 512 MB) | 512 MB is tight with parsing; parser child has its own memory budget | Render workspace, deploy hook |
| Render worker | Jobs + ingestion | Starter | $7/mo; bills while idle | same RAM caveat | same |
| Render Key Value (Redis) | Sessions, rate limits | Free | $0 (25 MB, **no persistence**: restart ⇒ everyone signs in again, counters reset); paid from $10/mo (256 MB) | Fine for staging; production needs paid + persistence decision | same |
| ClamAV (Render private service) | Malware scan | Pro (4 GB) | **$85/mo if always on** (pricing page snapshot; unconfirmed by 2nd source); billed per second ⇒ suspend when idle (~$0.12/h). While suspended, uploads are *held* unscanned (tested behavior), not indexed | Dominant cost; 2 GB plan unreliable per ClamAV docs | same |
| Auth0 | OIDC + MFA | Free tenant | $0 up to 25k MAU, 5 orgs per pricing page. **MFA on Free is unclear (sources conflict) — verify in the tenant first.** If not available: B2C Essentials from $35/mo (500 MAU) | MFA is a hard requirement for owner/admin; do not weaken the app check to fit a plan | Tenant admin (you), app + API creation |
| AI providers | Explain/Ask | **Leave unconfigured** | $0. If enabled, spend is capped by `VAND_AI_ORG_DAILY_TOKEN_BUDGET` (tokens) + per-user limits; USD needs a dated `VAND_AI_PRICING_JSON` from provider pricing | No live verification until a key is provisioned in a secret store | Provider key via secret manager (never chat/Git) |

**Always-on floor ≈ $14/mo** (two Render Starters; everything else free). ClamAV adds ≈ $0.12/h while running (≈ $85/mo if left on). A realistic acceptance-test month (ClamAV up ~10 h) ≈ **$15–16**. Auth0 Essentials (+$35) only if Free lacks MFA.

## Can anything share infrastructure safely?
- Same Cloudflare **account** is fine (separate Worker/bucket/token). Same Neon **project** is not (separate project; roles/RLS/backups are per-database).
- Do not reuse other products' R2 buckets or Neon projects.
- Worker + API may share one Render workspace; keep separate services so the worker/ClamAV can scale and be suspended independently.

## Scaling concerns
Neon free compute suspends (latency spike after idle; readiness checks wake it); Render Starter single instance (no HA); Redis free tier loses state on restart; ClamAV reload pauses scans (`ConcurrentDatabaseReload no` trades memory for brief scan blocking); Worker free tier 100k requests/day.

## Sources
[Render pricing](https://render.com/pricing) · [Render compute plans](https://render.com/docs/compute-plans) · [Neon pricing](https://neon.com/pricing) · [Neon plans](https://neon.com/docs/introduction/plans) · [Cloudflare R2 pricing](https://developers.cloudflare.com/r2/pricing/) · [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/) · [Auth0 pricing](https://auth0.com/pricing) · [ClamAV Docker docs](https://docs.clamav.net/manual/Installing/Docker.html)
