#!/bin/bash
# LOCAL REHEARSAL of the staging topology (does NOT count as live staging verification):
#   browser -> :5180 (Vercel emulation: dist + vercel.json headers + the real gateway code) -> API :8001 (oidc, origin auth,
#   clamd scanning REQUIRED) + worker -> Postgres/Redis/ClamAV on localhost; test OIDC issuer on :9000.
# Prereqs: roles from infra/database/roles.sql, an EMPTY database vand_rehearsal owned by vand_owner, Redis on :6379,
# clamd on :3310 (e.g. `docker run -d -p 3310:3310 clamav/clamav:stable`), `npm run build` done in apps/web, PY=<python>.
# Then: BASE_URL=http://localhost:5180 IDP=test-issuer EXPECT_SCAN=clean REQUESTER_EMAIL=req@rehearsal.example.com \
#       APPROVER_EMAIL=appr@rehearsal.example.com AUDITOR_EMAIL=aud@rehearsal.example.com OUTSIDER_EMAIL=out@rehearsal.example.com \
#       node tests/staging/acceptance.mjs
set -euo pipefail
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${PY:-python}"
LOG="${LOG_DIR:-/tmp}"
SECRET="$($PY -c 'import secrets;print(secrets.token_urlsafe(32))')"
DB="postgresql+psycopg://vand_owner:dev_owner_pw@localhost:5432/vand_rehearsal"   # pragma: allowlist secret (local dev role)
APP_DB="postgresql+asyncpg://vand_app:dev_app_pw@localhost:5432/vand_rehearsal"            # pragma: allowlist secret (local dev role)
WORKER_DB="postgresql+asyncpg://vand_worker:dev_worker_pw@localhost:5432/vand_rehearsal"   # pragma: allowlist secret (local dev role)
cd "$HERE/services/api"
VAND_ENV=local VAND_MIGRATION_DATABASE_URL="$DB" $PY -m alembic upgrade head >/dev/null
PGPASSWORD=dev_owner_pw psql -q -h localhost -U vand_owner -d vand_rehearsal -v ON_ERROR_STOP=1 -f "$HERE/tests/staging/seed_rehearsal.sql"
TEST_ISSUER=http://localhost:9000 nohup $PY -c "
import uvicorn; from tests.oidc_issuer import TestIssuer
uvicorn.run(TestIssuer().app, port=9000, log_level='warning')" > "$LOG/rehearsal-idp.log" 2>&1 &
export VAND_ENV=local VAND_AUTH_MODE=oidc VAND_OIDC_ISSUER=http://localhost:9000 VAND_OIDC_AUDIENCE=https://api.vand.test \
  VAND_OIDC_JWKS_URL=http://localhost:9000/jwks.json VAND_OIDC_CLIENT_ID=vand-web VAND_OIDC_CLIENT_SECRET=s3cret \
  VAND_PUBLIC_BASE_URL=http://localhost:5180 VAND_CORS_ORIGINS=http://localhost:5180 \
  VAND_DATABASE_URL="$APP_DB" \
  VAND_WORKER_DATABASE_URL="$WORKER_DB" \
  VAND_REDIS_URL=redis://localhost:6379/3 VAND_STORAGE_BACKEND=local VAND_STORAGE_LOCAL_DIR="$LOG/rehearsal-objects" \
  VAND_SCANNER_BACKEND=clamd VAND_SCAN_REQUIRED=true VAND_CLAMD_HOST=localhost VAND_CLAMD_PORT=3310 \
  VAND_ORIGIN_AUTH_SECRET="$SECRET" VAND_MAX_UPLOAD_BYTES=4194304 \
  VAND_SESSION_ENCRYPTION_KEY="$($PY -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
unset VAND_MIGRATION_DATABASE_URL
nohup $PY -m uvicorn app.main:create_app --factory --port 8001 > "$LOG/rehearsal-api.log" 2>&1 &
nohup $PY -m app.worker > "$LOG/rehearsal-worker.log" 2>&1 &
cd "$HERE"
ORIGIN_AUTH_SECRET="$SECRET" PORT=5180 API_LOCAL=http://127.0.0.1:8001 \
  nohup node --experimental-strip-types --no-warnings tests/staging/local_gateway.mjs > "$LOG/rehearsal-gateway.log" 2>&1 &
bash scripts/wait_for.sh http://localhost:9000/.well-known/openid-configuration 60
bash scripts/wait_for.sh http://localhost:8001/healthz 60
bash scripts/wait_for.sh http://localhost:5180/ 60
echo "rehearsal stack up on http://localhost:5180"
