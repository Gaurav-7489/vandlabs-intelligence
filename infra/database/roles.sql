-- Run once per cluster as a superuser. Passwords below are LOCAL DEV ONLY; use secret-managed values elsewhere.
-- vand_owner : owns schema, runs migrations (never used by the running API).
-- vand_app   : API runtime. NOSUPERUSER NOBYPASSRLS so Row-Level Security applies.
-- vand_worker: background worker runtime. Same RLS, plus a cross-tenant policy on `jobs` only (claiming work).
CREATE ROLE vand_owner LOGIN PASSWORD 'dev_owner_pw' CREATEDB;
CREATE ROLE vand_app LOGIN PASSWORD 'dev_app_pw' NOSUPERUSER NOBYPASSRLS;
CREATE ROLE vand_worker LOGIN PASSWORD 'dev_worker_pw' NOSUPERUSER NOBYPASSRLS;
-- vand_backup: READ-ONLY, BYPASSRLS. Needed because FORCE RLS makes owner pg_dump fail. Its credential lives ONLY in the backup job.
-- It must never be used by the API/worker (the startup safety check refuses BYPASSRLS roles).
CREATE ROLE vand_backup LOGIN PASSWORD 'dev_backup_pw' NOSUPERUSER BYPASSRLS;  -- pragma: allowlist secret (local dev only)

-- Neon: create these with plain SQL (CREATE ROLE ... NOSUPERUSER NOBYPASSRLS), not via console role helpers that grant neon_superuser.
-- After migrations, grants are applied by the migration itself. Verify with GET /readyz (edge-authenticated): checks.db_role == "ok".
