#!/usr/bin/env bash
# Logical backup + restore drill. Dumps SOURCE as the read-only BYPASSRLS backup role, restores into a FRESH database,
# then verifies: per-table row counts, RLS enabled+forced, policy count, audit immutability triggers, runtime grants,
# and that the app role is still tenant-isolated on the restored copy. Exits non-zero on any mismatch.
#   BACKUP_URL   postgresql://vand_backup:...@host/db        (read-only, BYPASSRLS)
#   ADMIN_URL    postgresql://<superuser-or-restore-role>@host/postgres   (creates/drops the scratch DB)
#   APP_PASSWORD password of vand_app (to prove isolation on the restored DB)
set -euo pipefail
: "${BACKUP_URL:?}" "${ADMIN_URL:?}" "${APP_PASSWORD:?}"
SCRATCH="vand_restore_drill_$(date +%s)"
DUMP="$(mktemp -d)/drill.pgc"
HOSTPART="$(echo "$ADMIN_URL" | sed -E 's#^postgresql://[^@]*@([^/]+)/.*#\1#')"
restore_url() { echo "$ADMIN_URL" | sed -E "s#/[^/?]+(\?|$)#/$SCRATCH\1#"; }
# Counting must use a BYPASSRLS reader on BOTH sides: under FORCE RLS even the owner sees zero tenant rows.
restore_reader_url() { echo "$BACKUP_URL" | sed -E "s#/[^/?]+(\?|$)#/$SCRATCH\1#"; }

# Version guard: a dump made by a NEWER client emits settings (e.g. transaction_timeout, PG17+) that an OLDER server rejects on restore.
CLIENT_MAJOR=$(pg_restore --version | grep -oE '[0-9]+' | head -1)
SERVER_MAJOR=$(psql "$ADMIN_URL" -Atc "SHOW server_version_num" | cut -c1-2)
if [ "$CLIENT_MAJOR" -gt "$SERVER_MAJOR" ]; then
  echo "pg client $CLIENT_MAJOR is newer than server $SERVER_MAJOR: install postgresql-client-$SERVER_MAJOR (restores must use a matching client)" >&2; exit 2
fi
echo "   client $CLIENT_MAJOR / server $SERVER_MAJOR"
echo "1/5 dump (custom format) as backup role"
pg_dump "$BACKUP_URL" -Fc -f "$DUMP"   # set -e + no pipe: a failed dump aborts the drill
test -s "$DUMP"
echo "   size: $(stat -c %s "$DUMP") bytes; sha256: $(sha256sum "$DUMP" | cut -c1-16)…"

echo "2/5 restore into fresh database $SCRATCH"
psql "$ADMIN_URL" -qc "CREATE DATABASE $SCRATCH OWNER vand_owner"
trap 'psql "$ADMIN_URL" -qc "DROP DATABASE IF EXISTS $SCRATCH" >/dev/null 2>&1 || true' EXIT
pg_restore -d "$(restore_url)" --exit-on-error "$DUMP"

echo "3/5 compare row counts per table"
q_counts="SELECT string_agg(t||'='||n, ',' ORDER BY t) FROM (SELECT c.relname t, (xpath('/row/c/text()', query_to_xml('select count(*) as c from public.'||quote_ident(c.relname), false, true, '')))[1]::text::int n FROM pg_class c JOIN pg_namespace s ON s.oid=c.relnamespace WHERE s.nspname='public' AND c.relkind='r') x"
SRC=$(psql "$BACKUP_URL" -Atc "$q_counts")
DST=$(psql "$(restore_reader_url)" -Atc "$q_counts")
[ "$SRC" = "$DST" ] || { echo "ROW COUNT MISMATCH"; echo "src: $SRC"; echo "dst: $DST"; exit 1; }
echo "   identical: $SRC" | cut -c1-200

echo "4/5 verify security structure survived"
psql "$(restore_url)" -Atc "SELECT count(*) FROM pg_class c JOIN pg_namespace s ON s.oid=c.relnamespace WHERE s.nspname='public' AND c.relkind='r' AND c.relname<>'alembic_version' AND NOT (c.relrowsecurity AND c.relforcerowsecurity) AND c.relname<>'users'" | grep -qx 0 || { echo "RLS NOT FORCED on some table"; exit 1; }
SRC_POL=$(psql "$BACKUP_URL" -Atc "SELECT count(*) FROM pg_policies WHERE schemaname='public'"); DST_POL=$(psql "$(restore_url)" -Atc "SELECT count(*) FROM pg_policies WHERE schemaname='public'")
[ "$SRC_POL" = "$DST_POL" ] || { echo "POLICY COUNT MISMATCH $SRC_POL vs $DST_POL"; exit 1; }
psql "$(restore_url)" -Atc "SELECT count(*) FROM pg_trigger WHERE tgname IN ('audit_no_update','audit_no_truncate')" | grep -qx 2 || { echo "AUDIT TRIGGERS MISSING"; exit 1; }
psql "$(restore_url)" -Atc "SELECT has_table_privilege('vand_app','documents','SELECT') AND NOT has_table_privilege('vand_app','audit_events','UPDATE')" | grep -qx t || { echo "RUNTIME GRANTS WRONG"; exit 1; }
echo "   RLS forced on all tenant tables; $DST_POL policies; audit triggers present; vand_app grants correct"

echo "5/5 app role is still tenant-isolated on the restored copy"
APP_URL="postgresql://vand_app:${APP_PASSWORD}@${HOSTPART}/${SCRATCH}"
TOTAL=$(psql "$(restore_reader_url)" -Atc "SELECT count(*) FROM documents")
SEEN=$(psql "$APP_URL" -Atc "SELECT count(*) FROM documents")
[ "$SEEN" = "0" ] || { echo "ISOLATION BROKEN: app role sees $SEEN rows without tenant context"; exit 1; }
echo "   documents: $TOTAL rows in restore; app role without tenant context sees $SEEN"
echo "DRILL PASSED ($SCRATCH dropped on exit)"
