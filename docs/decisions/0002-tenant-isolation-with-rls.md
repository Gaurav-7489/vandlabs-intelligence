# ADR-0002: Tenant isolation via PostgreSQL RLS + application checks
**Status:** accepted. Defense in depth: (1) membership validated server-side, (2) permission checks, (3) RLS with `FORCE` and a non-owner runtime role.
Gotchas encoded in code/tests: `nullif(current_setting(..), '')` (GUC reads back `''` on reused pooled connections); `INSERT … RETURNING` needs SELECT-policy
visibility (audit inserts use plain SQL); the table owner is also subject to RLS, so migrations/ops use a separate role and tests inspect via the right role.
Transaction-local `set_config` is compatible with Neon's pooled (transaction-mode) endpoint when `VAND_DB_DISABLE_STATEMENT_CACHE=true`.
