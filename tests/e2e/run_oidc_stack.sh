#!/bin/bash
# Starts: test OIDC issuer (:9000), API in oidc mode (:8001), then vite (:5174) proxying /api -> :8001. Local test use only.
set -e
cd "$(dirname "$0")/../../services/api"
export TEST_ISSUER=http://localhost:9000
nohup ../../.venv/bin/python -c "
import uvicorn; from tests.oidc_issuer import TestIssuer
uvicorn.run(TestIssuer().app, port=9000, log_level='warning')" > /tmp/idp.log 2>&1 &
export VAND_ENV=local VAND_AUTH_MODE=oidc VAND_OIDC_ISSUER=http://localhost:9000 VAND_OIDC_AUDIENCE=https://api.vand.test \
  VAND_OIDC_JWKS_URL=http://localhost:9000/jwks.json VAND_OIDC_CLIENT_ID=vand-web VAND_OIDC_CLIENT_SECRET=s3cret \
  VAND_PUBLIC_BASE_URL=http://localhost:5174 VAND_CORS_ORIGINS=http://localhost:5174 \
  VAND_SESSION_ENCRYPTION_KEY="$(../../.venv/bin/python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
nohup ../../.venv/bin/uvicorn app.main:create_app --factory --port 8001 > /tmp/api-oidc.log 2>&1 &
cd ../../apps/web && VITE_API_TARGET=http://localhost:8001 nohup npx vite --port 5174 > /tmp/vite-oidc.log 2>&1 &
sleep 5; echo started
