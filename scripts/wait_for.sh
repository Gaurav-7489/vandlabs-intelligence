#!/usr/bin/env bash
# Wait until URL returns HTTP 2xx/3xx, up to TIMEOUT seconds. Replaces fixed sleeps (CI run on a27cf71 failed on a race).
url="$1"; timeout="${2:-60}"
for _ in $(seq 1 "$timeout"); do
  if curl -fs -o /dev/null "$url"; then echo "ready: $url"; exit 0; fi
  sleep 1
done
echo "TIMEOUT waiting for $url" >&2; exit 1
