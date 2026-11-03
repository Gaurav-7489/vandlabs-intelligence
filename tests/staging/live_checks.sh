#!/bin/bash
# Live staging boundary checks (run after deployment; part of the A9 acceptance run). Synthetic/no data, read-mostly.
#   WEB_URL      https://vandlabs-intelligence.vercel.app        (required)
#   API_URL      https://<Render API host>                         (required: direct-origin checks)
#   PREVIEW_URL  https://<a Vercel preview deployment URL>         (optional: preview must NOT reach staging)
#   ORIGIN_AUTH_SECRET  (optional; read from env, never printed)   enables the /readyz db_role check on the origin
# Exit code = number of failed checks. Prints no secrets.
set -uo pipefail
WEB="${WEB_URL:?WEB_URL required}"; WEB="${WEB%/}"
API="${API_URL:?API_URL required}"; API="${API%/}"
fails=0
check() { # name expected actual
  if [ "$2" = "$3" ]; then echo "PASS  $1 ($3)"; else echo "FAIL  $1: expected $2, got $3"; fails=$((fails+1)); fi
}
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$@"; }

check "gateway serves the API (auth config)" 200 "$(code "$WEB/api/v1/auth/config")"
check "auth mode is oidc" yes "$(curl -s --max-time 60 "$WEB/api/v1/auth/config" | grep -q '"oidc"' && echo yes || echo no)"
check "anonymous session via gateway" 200 "$(code "$WEB/api/v1/auth/session")"
check "responses are not cacheable" yes "$(curl -sI --max-time 60 "$WEB/api/v1/auth/session" | grep -qi '^cache-control: no-store' && echo yes || echo no)"
check "direct origin without secret is refused" 403 "$(code "$API/api/v1/auth/config")"
check "direct origin with a guessed secret is refused" 403 "$(code -H 'x-origin-auth: guessed-not-the-secret-000000000000' "$API/api/v1/auth/config")"
check "origin liveness" 200 "$(code "$API/healthz")"
check "path traversal through the gateway is refused" 404 "$(code "$WEB/api/gateway?__vand_path=..%2F..%2Freadyz")"
check "non-v1 API paths are not routed" 404 "$(code "$WEB/api/readyz")"
check "cross-site write without session/CSRF is refused" 401 "$(code -X POST -H 'origin: https://evil.example' -H 'content-type: application/json' -d '{}' "$WEB/api/v1/decisions")"

tmp="$(mktemp)"; head -c 4600000 /dev/zero > "$tmp"
big="$(code -X POST -H 'content-type: application/octet-stream' --data-binary @"$tmp" "$WEB/api/v1/documents")"; rm -f "$tmp"
check "oversized body (4.6 MB) rejected with 413 (gateway or Vercel)" 413 "$big"

if [ -n "${PREVIEW_URL:-}" ]; then
  check "preview deployment cannot reach staging" 503 "$(code "${PREVIEW_URL%/}/api/v1/auth/session")"
else
  echo "SKIP  preview isolation (set PREVIEW_URL)"
fi
if [ -n "${ORIGIN_AUTH_SECRET:-}" ]; then
  ready="$(curl -s --max-time 60 -H "x-origin-auth: $ORIGIN_AUTH_SECRET" "$API/readyz")"
  for k in database db_role redis; do
    check "readyz $k" ok "$(printf '%s' "$ready" | python3 -c "import json,sys;print(json.load(sys.stdin).get('checks',{}).get('$k','missing'))" 2>/dev/null || echo unparsable)"
  done
else
  echo "SKIP  /readyz db_role (set ORIGIN_AUTH_SECRET in the environment; it is never printed)"
fi
echo "failed checks: $fails"
exit "$fails"
