-- Neon staging bootstrap (run ONCE per branch, branch-first: a throwaway branch before the default branch).
-- Connect as the Neon project owner role (e.g. neondb_owner) over the DIRECT endpoint, database `neondb`.
-- Passwords are psql variables taken from the environment, never written to this file or to shell history:
--   export VAND_OWNER_PW="$(openssl rand -base64 33)" VAND_APP_PW="$(openssl rand -base64 33)" \
--          VAND_WORKER_PW="$(openssl rand -base64 33)" VAND_BACKUP_PW="$(openssl rand -base64 33)"
--   psql "$NEON_OWNER_DIRECT_URL" -v ON_ERROR_STOP=1 -v owner_pw="$VAND_OWNER_PW" -v app_pw="$VAND_APP_PW" \
--        -v worker_pw="$VAND_WORKER_PW" -v backup_pw="$VAND_BACKUP_PW" -f infra/database/neon_bootstrap.sql
-- Then store the four passwords in the secret manager (GitHub environment secrets / Render env), and unset them.
--
-- Why plain SQL: roles created in the Neon console are members of neon_superuser. These are not (the API refuses to
-- start if its role can reach a privileged role). Tested against PostgreSQL 17 as a NON-superuser CREATEROLE/CREATEDB role.
\set ON_ERROR_STOP on
-- Pre-flight (prints, changes nothing): the creator needs CREATEROLE + CREATEDB, and BYPASSRLS for vand_backup.
SELECT current_user AS creator, rolcreaterole AS createrole, rolcreatedb AS createdb, rolbypassrls AS bypassrls
FROM pg_roles WHERE rolname = current_user;

BEGIN;  -- all four roles or none
CREATE ROLE vand_owner  LOGIN PASSWORD :'owner_pw'  NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
CREATE ROLE vand_app    LOGIN PASSWORD :'app_pw'    NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;
CREATE ROLE vand_worker LOGIN PASSWORD :'worker_pw' NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB;

-- vand_backup must be BYPASSRLS (FORCE RLS makes pg_dump fail otherwise). PostgreSQL only lets a role that itself has
-- BYPASSRLS create one. If this statement fails on Neon, STOP: backups need a different design; do not weaken RLS.
CREATE ROLE vand_backup LOGIN PASSWORD :'backup_pw' NOSUPERUSER BYPASSRLS NOCREATEROLE NOCREATEDB;
COMMIT;

-- Dedicated database owned by vand_owner (migrations create tables as vand_owner, so runtime roles never own them).
-- PG16+: the creating role must be able to SET ROLE vand_owner to give it the database.
GRANT vand_owner TO CURRENT_USER WITH INHERIT FALSE, SET TRUE;
CREATE DATABASE vand_staging OWNER vand_owner;
REVOKE vand_owner FROM CURRENT_USER;
REVOKE ALL ON DATABASE vand_staging FROM PUBLIC;
GRANT CONNECT ON DATABASE vand_staging TO vand_app, vand_worker, vand_backup;

\connect vand_staging
-- PG15+ already denies CREATE on public to PUBLIC; make it explicit, and let only vand_owner create objects.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO vand_app, vand_worker, vand_backup;
\echo 'bootstrap done: next run migrations as vand_owner (deploy-staging migrate job), then scripts/verify_staging_db.sql'
