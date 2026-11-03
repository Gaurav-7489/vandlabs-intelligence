-- Read-only verification of a staging database (e.g. a Neon branch of shy-leaf-28061787) AFTER roles + migrations.
-- Run as the project owner (or vand_owner) over the DIRECT endpoint:
--   psql "$OWNER_DIRECT_URL" -v ON_ERROR_STOP=1 -f scripts/verify_staging_db.sql
-- Every check prints a row; any row with ok = false is a blocker. Prints no secrets. Changes nothing.
\pset footer off
\echo '== identity (confirm this is the VandLabs Intelligence staging database, not another product)'
SELECT current_database() AS database, current_user AS connected_as, version() AS server,
       (SELECT version_num FROM alembic_version) AS migration_head;

\echo '== runtime/backup role attributes'
WITH expected(role, want_bypassrls) AS (VALUES ('vand_app', false), ('vand_worker', false), ('vand_backup', true))
SELECT e.role, r.rolname IS NOT NULL AS exists, r.rolsuper AS superuser, r.rolbypassrls AS bypassrls, r.rolcreaterole AS createrole,
       r.rolcreatedb AS createdb,
       (r.rolname IS NOT NULL AND NOT r.rolsuper AND NOT r.rolcreaterole AND NOT r.rolcreatedb AND r.rolbypassrls = e.want_bypassrls) AS ok
FROM expected e LEFT JOIN pg_roles r ON r.rolname = e.role ORDER BY 1;

\echo '== no runtime/backup role can SET ROLE into a privileged role (neon_superuser, superuser, BYPASSRLS, pg_*_all_data)'
SELECT m.rolname AS role, string_agg(p.rolname, ', ') AS privileged_memberships, count(p.oid) = 0 AS ok
FROM pg_roles m
LEFT JOIN pg_roles p ON p.oid <> m.oid AND pg_has_role(m.oid, p.oid, 'MEMBER')
   AND (p.rolsuper OR p.rolbypassrls OR p.rolname IN ('neon_superuser', 'pg_write_all_data', 'pg_read_all_data'))
WHERE m.rolname IN ('vand_app', 'vand_worker', 'vand_backup')
GROUP BY m.rolname ORDER BY 1;

\echo '== runtime roles own no tables (ownership bypasses FORCE RLS only for owners; must be vand_owner)'
SELECT tableowner, count(*) AS tables, tableowner NOT IN ('vand_app', 'vand_worker', 'vand_backup') AS ok
FROM pg_tables WHERE schemaname = 'public' GROUP BY tableowner ORDER BY 1;

\echo '== RLS enabled AND forced on every tenant table (expect 16 rows, all ok)'
SELECT c.relname AS table, c.relrowsecurity AS rls, c.relforcerowsecurity AS forced,
       (SELECT count(*) FROM pg_policies p WHERE p.tablename = c.relname AND p.schemaname = 'public') AS policies,
       (c.relrowsecurity AND c.relforcerowsecurity) AS ok
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relname IN ('memberships','documents','document_chunks','commitments','tasks','insights','decisions',
  'approvals','executions','outcomes','ai_usage','jobs','audit_events','organizations','users','insight_explanations')
ORDER BY 1;

\echo '== backup role is read-only (no INSERT/UPDATE/DELETE/TRUNCATE on any table)'
SELECT count(*) FILTER (WHERE has_table_privilege('vand_backup', c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE')) AS writable_tables,
       count(*) FILTER (WHERE has_table_privilege('vand_backup', c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE')) = 0 AS ok
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind = 'r';

\echo '== runtime roles cannot change the schema'
SELECT r AS role, has_schema_privilege(r, 'public', 'CREATE') AS can_create_in_public,
       NOT has_schema_privilege(r, 'public', 'CREATE') AS ok
FROM unnest(ARRAY['vand_app', 'vand_worker', 'vand_backup']) AS r ORDER BY 1;

\echo '== audit log is append-only (triggers present)'
SELECT count(*) AS audit_triggers, count(*) > 0 AS ok FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname = 'audit_events' AND NOT t.tgisinternal;
