# Backups and restore

**Finding (verified):** with `FORCE ROW LEVEL SECURITY`, a logical `pg_dump` as the table owner **fails** ("query would be affected by row-level security policy"); a piped/backgrounded dump can leave a partial file that looks valid. Logical backups therefore use a dedicated **read-only `BYPASSRLS` role `vand_backup`**, whose credential exists only in the backup job (never API/worker; the runtime safety check refuses BYPASSRLS roles).

**Drill (implemented, run locally and in CI on every push):** `scripts/backup_restore_drill.sh` dumps as `vand_backup`, restores into a fresh database, and fails unless per-table row counts match, RLS is enabled+forced on every tenant table, all policies and audit-immutability triggers exist, runtime grants are correct, and `vand_app` still sees zero tenant rows without tenant context. Local result 2026-11-03: PASSED (17 tables, 20 policies).

**Staging (prepared, not run):** `.github/workflows/backup-staging.yml` — dump → GPG AES-256 symmetric encryption → private R2 bucket. Neon Free retains only ~6 h of history, so this is the real backup. **Use a pg client matching the server major version** (Neon staging is PG 17); a newer client produces dumps an older server cannot restore (seen in CI: `transaction_timeout`). Restore = download → decrypt → `pg_restore` into a new Neon branch/DB as a privileged role → run the drill checks → repoint `VAND_DATABASE_URL`.

**Not yet defined:** RPO/RTO (needs business input), retention period, restore drill against Neon, R2 object versioning on the uploads bucket. Redis is not backed up (sessions/counters only).
