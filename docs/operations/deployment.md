# Deployment — staging (prepared; NOT deployed or externally verified)

Topology ([ADR 0007](../decisions/0007-vercel-same-origin-api-gateway.md)): browser → existing Vercel project
`vandlabs-intelligence` (SPA + `/api/v1/*` gateway function) → Render API (`render.yaml`) + Render worker → Neon
(`shy-leaf-28061787`, database `vand_staging`), Render Key Value, R2, private ClamAV; Auth0 for sign-in.
The Vercel environment is called "Production" by Vercel, but everything here is **staging** with synthetic data only.
Paid steps (Render API/worker A4, ClamAV A6) need the owner's approval first.

## Order of operations
1. **Neon (branch first).** Create a throwaway branch (e.g. `bootstrap-check`) of the default branch. On it, run
   `infra/database/neon_bootstrap.sql` (generated passwords via psql variables; see the file header), then migrations
   as `vand_owner` against `vand_staging`, then `scripts/verify_staging_db.sql` — every row must be `ok = t`.
   Delete the branch, then repeat on the default branch with **new** passwords stored in the secret manager.
   If `CREATE ROLE vand_backup ... BYPASSRLS` fails ("Only roles with the BYPASSRLS attribute may create…"), stop:
   backups need another design; do not weaken RLS.
2. **R2:** private buckets + scoped tokens (checklist step 3). **Auth0:** per [auth0-setup.md](auth0-setup.md).
3. **Render (after A4/A6 approval):** New Blueprint from the repo → `render.yaml`. Fill every `sync: false` variable from
   the secret manager: pooled Neon URLs for `vand_app`/`vand_worker` (`VAND_DB_DISABLE_STATEMENT_CACHE=true` is set),
   R2 doc-bucket token, OIDC values, `VAND_SESSION_ENCRYPTION_KEY` (Fernet), `VAND_ORIGIN_AUTH_SECRET` (≥ 32 random chars).
   **No owner/migration URL in Render** — the API refuses to start if one is present, or if its DB role is unsafe.
4. **Migrations:** GitHub → Actions → *Deploy staging (manual)* → `migrate` job (environment `staging`, reviewer approval,
   secret `STAGING_OWNER_DATABASE_URL` = Neon direct endpoint as `vand_owner`). Then once, from a trusted machine:
   `OWNER_DATABASE_URL=<direct owner URL> python -m app.cli create-platform-admin <owner email>`.
5. **Vercel:** Production-scope env vars `VAND_API_ORIGIN=https://<render api host>` and `VAND_ORIGIN_AUTH_SECRET`
   (same value as Render). Not for Preview. Redeploy `main` after the PR is merged (owner decision).
6. **Smoke + boundary checks:** `tests/staging/live_checks.sh` (direct origin 403, gateway 200, 413, traversal 404,
   preview 503 with `PREVIEW_URL`, `/readyz` incl. `db_role` with `ORIGIN_AUTH_SECRET` in env). Then, with A9 approval,
   `tests/staging/acceptance.mjs` and `tests/staging/scanner_checks.mjs OUTAGE=1`.

## Scanner operating schedule (A6)
`vand-clamav-staging` stays **suspended** outside test windows (Render dashboard → service → Settings → Suspend /
Resume, or the Render API). While suspended, uploads are accepted, kept **unindexed** with `scan_pending`, and never
marked clean. The worker retries held jobs every 30 min (`VAND_SCAN_HOLD_RETRY_SECONDS`) without spending normal retry
attempts, and PINGs clamd every 60 s without touching Postgres; when ClamAV answers again it releases all held uploads
automatically. Holds older than 7 days dead-letter (file stays unindexed; re-upload or *Reprocess*). ClamAV needs
~1–2 min after resume to load signatures before it answers.

## Rollback
- **Frontend/gateway:** Vercel → Deployments → *Instant Rollback* to the previous production deployment. To cut the
  SPA off from the API immediately, remove `VAND_API_ORIGIN` (gateway then fails closed with 503) and redeploy.
- **API / worker:** Render → service → Events → *Rollback* to the previous deploy (same image for both; roll back both).
- **Configuration:** Render keeps env var history only in the dashboard audit; record changes in the PR/issue.
- **Schema:** migrations are additive (expand/contract). **Do not assume downgrades are safe**: `0001` downgrade is
  blocked without `VAND_ALLOW_DESTRUCTIVE_DOWNGRADE`; `0002` downgrade drops `insight_explanations` and scan columns.
  Preferred schema rollback = restore the latest encrypted backup into a **new Neon branch**, verify with the drill
  checks + `scripts/verify_staging_db.sql`, then repoint the pooled URLs. Neon Free history (~6 h) also allows a
  branch from a point in time.
- **Secrets:** rotate `VAND_ORIGIN_AUTH_SECRET` by setting the new value on Render and Vercel together, then redeploy both.

## Edge protection (not yet done)
On `*.vercel.app`: Vercel Firewall rules where the plan allows; the API's Redis-backed rate limits always apply.
Full Cloudflare WAF needs a custom domain (not approved).

## Backups / DR
`.github/workflows/backup-staging.yml` (prepared, not run): `pg_dump` as `vand_backup` with a PG 17 client → GPG
AES-256 → private R2 backup bucket (write-only token). Restores need a separate, temporary read token. RPO/RTO not
yet defined. Redis holds sessions and rate counters only (loss = users sign in again).
