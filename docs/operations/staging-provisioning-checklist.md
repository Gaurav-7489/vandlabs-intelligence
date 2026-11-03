# Staging provisioning checklist (low-cost)

Nothing here has been executed. Costs are from vendor pricing pages read 2026-11-03 (see staging-resource-plan.md); re-check before purchase.
Legend: **[APPROVE]** needs your explicit approval (cost or account change) · **[YOU]** only you can do it (owner login, billing, secrets) · **[CLAUDE]** I can do it once access is granted.

## Approvals needed (summary)
| # | Approval | Recurring cost | Why |
|---|---|---|---|
| A1 | Create a **new** Neon project `vandlabs-intelligence-staging` in your existing free org (region: Singapore, matching your other projects) | $0 (Free: 100 CU-h, 1 GB, scale-to-zero) | Separate from the Automobile Engine / AVIENDO projects |
| A2 | Create R2 bucket `vand-intel-staging-docs` (+ `vand-intel-staging-backups`) and two scoped API tokens in your existing Cloudflare account | $0 within free tier (10 GB-mo, 1M Class A, 10M Class B) | Private document + encrypted backup storage |
| A3 | Deploy Worker `vandlabs-intelligence-web-staging` (workers.dev URL) in the same Cloudflare account | $0 on Workers Free (100k Worker req/day) | Does not touch the 12 existing Workers |
| A4 | Render: API web service + background worker (Starter each) | **≈ $14/mo** ($7 + $7) | Python runtime |
| A5 | Render Key Value (free, 25 MB, no persistence) | $0 | Sessions + distributed rate limits |
| A6 | Render private service for ClamAV (4 GB plan), **suspended when not testing** | **≈ $0.12/h running; ≈ $85/mo if left on** | Real malware scanning (required by config in staging) |
| A7 | Auth0 staging tenant (Free). **If Free cannot enforce MFA**, B2C Essentials | $0, or **$35/mo** | MFA for owner/admin is a hard requirement |
| A8 | Leave AI providers **disabled** in staging (no keys) | $0 | Enable later only with a key in a secret store + a token budget |
| A9 | Run the 17-step acceptance test with synthetic users only | — | No customer data |
Expected: **≈ $14–16/mo** (ClamAV running ~10 h), +$35 only if Auth0 Free lacks MFA.

## Steps
1. **[YOU] GitHub**: create environment `staging` with required reviewers; add secrets later listed in step 9. Enable branch protection on `main` (require CI checks `api`, `web`, `secrets`, `e2e`).
2. **[APPROVE A1] Neon**: create project (PG 17). As the project owner run `infra/database/roles.sql` **with strong generated passwords** (never the dev ones). Verify the roles are *not* members of `neon_superuser` (`\du`). Record: direct URL (owner, migrations), pooled URLs (`vand_app`, `vand_worker`), direct URL for `vand_backup`.
3. **[APPROVE A2] R2**: buckets private (no public access, no custom domain). Token 1: Object Read & Write on `vand-intel-staging-docs` only. Token 2: Object Write on `vand-intel-staging-backups` only. Enable object versioning/lifecycle if available on your plan.
4. **[APPROVE A7] Auth0**: follow `docs/operations/auth0-setup.md`. First check in the tenant that MFA (OTP/WebAuthn) can be required on the plan; confirm the ID token carries `amr: ["mfa"]` after an MFA login. Create synthetic users: requester, approver, auditor, outsider (separate org), owner (MFA enrolled).
5. **[APPROVE A4–A6] Render**: connect the GitHub repo, apply `render.yaml` (Blueprint). Fill every `sync: false` variable from the secret manager. Generate: `VAND_SESSION_ENCRYPTION_KEY` (Fernet), `VAND_ORIGIN_AUTH_SECRET` (≥ 32 random chars). Use **pooled** Neon URLs + `VAND_DB_DISABLE_STATEMENT_CACHE=true`. Do **not** add any owner/migration URL (the app refuses to start if present).
6. **[CLAUDE] Migrations**: GitHub secret `STAGING_OWNER_DATABASE_URL` (direct endpoint) → run *Deploy staging (manual)* → `migrate` job (`alembic upgrade head` → 0004). Then create the first platform admin with `OWNER_DATABASE_URL=… python -m app.cli create-platform-admin <your email>`.
7. **[APPROVE A3] Cloudflare Worker**: set `API_ORIGIN` in `apps/web/wrangler.jsonc` to the Render API URL; `wrangler secret put ORIGIN_AUTH_SECRET` (same value as Render); `npm run build && wrangler deploy` (already validated with `--dry-run`). Set `VAND_PUBLIC_BASE_URL` / `VAND_CORS_ORIGINS` on Render to the Worker URL; Auth0 callback = `<worker URL>/api/v1/auth/callback`.
8. **[YOU] Cloudflare edge** (workers.dev has limited zone features; a custom domain on your zone enables full WAF): managed WAF ruleset, rate-limiting rule on `/api/v1/auth/*` and `/api/v1/documents`, Bot Fight Mode on the zone, Turnstile only if login abuse appears.
9. **[YOU] GitHub secrets for workflows**: `CLOUDFLARE_API_TOKEN` (Workers deploy, scoped), `CLOUDFLARE_ACCOUNT_ID`, `RENDER_DEPLOY_HOOK_API`, `RENDER_DEPLOY_HOOK_WORKER`, `STAGING_OWNER_DATABASE_URL`, `STAGING_BACKUP_DATABASE_URL`, `BACKUP_ENCRYPTION_PASSPHRASE`, `R2_BACKUP_ACCESS_KEY_ID`, `R2_BACKUP_SECRET_ACCESS_KEY`, `R2_ENDPOINT`; variable `STAGING_WEB_URL`.
10. **[CLAUDE] Verification** (no customer data):
    - `GET /readyz` with `X-Origin-Auth` ⇒ `database ok`, `redis ok`, **`db_role ok` on Neon** (the key RLS check).
    - Direct call to the Render URL without the secret ⇒ 403.
    - Run `tests/staging/acceptance.mjs` with `IDP=auth0 EXPECT_SCAN=clean` (17 steps, real ClamAV, real Auth0, real R2/Neon).
    - Run *Backup staging* once, then restore into a Neon branch and run the drill checks.
    - Upload an EICAR test file ⇒ quarantined, not searchable.
    - Suspend ClamAV ⇒ uploads held as `scan_pending`; resume ⇒ processed.
    - Review Render logs for errors; check `/api/v1/ops/metrics` (platform admin).
11. **[YOU] Rollback plan**: Render "rollback to previous deploy"; `wrangler rollback`; migrations are additive (0002–0004 downgrades exist and were not destructive except 0001).

## Not in scope for staging approval
Production resources, paid Neon/Render plans beyond the above, any real customer data, enabling AI providers, merging PR #1.
