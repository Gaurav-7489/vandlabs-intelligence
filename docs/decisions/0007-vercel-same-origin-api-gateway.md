# ADR 0007 — Vercel same-origin API gateway (supersedes the Cloudflare web Worker for staging)

Status: accepted (Phase 1.7) · Date: 2026-11-03 · Revised: Node.js runtime

## Context
The SPA is already deployed on the existing Vercel project `vandlabs-intelligence` (root `apps/web`). It calls `/api/v1/*`
on its own origin (backend-for-frontend: `__Host-` session cookie, CSRF token + Origin allow-list, OIDC callback at
`<web origin>/api/v1/auth/callback`). The FastAPI origin rejects any request without a valid `X-Origin-Auth` secret
(403), and trusts `X-Vand-Client-IP` only when that secret is present. Before this change, Vercel served nothing on
`/api/*`, so every API call from the deployed site would 404.

Options considered:
1. **Vercel external rewrite** `/api/v1/:path*` → API origin. Simplest, but a rewrite cannot add the secret header, so
   origin auth would have to be turned off (direct origin access and client-IP spoofing come back). Rejected.
2. **Second frontend on a Cloudflare Worker** (the old A3 plan). Redundant with Vercel, a second public origin, and
   cookies/callbacks would have to pick one. Rejected for staging; the Worker code is kept but not deployed.
3. **Cross-origin API** (`api.<domain>`). Needs a custom domain (not approved), CORS with credentials and SameSite
   changes. Rejected.
4. **Vercel Function gateway** (Node.js runtime, Web `fetch` handler) that forwards `/api/v1/*` and adds `X-Origin-Auth`
   from a server-side env var. Chosen. (Initially written for the Edge runtime; changed because Vercel has deprecated Edge
   Functions and caps their request body at 4 MB — too small for a 4 MiB upload plus multipart framing.)

## Decision
`apps/web/vercel.json` rewrites `/api/v1/:path*` to `/api/gateway?__vand_path=:path*`; `apps/web/api/gateway.ts` (Node.js
runtime, `export default { fetch }`) calls `proxyApi` in `apps/web/src/edge/proxy.ts`, which:
- fails closed (503) when `VAND_API_ORIGIN`/`VAND_ORIGIN_AUTH_SECRET` are missing/weak or the origin is not https;
- refuses on non-production deployments (`VERCEL_ENV != production`) unless `VAND_GATEWAY_ALLOW_PREVIEW=true`;
- forwards only `/api/v1/...` with safe characters (no dot segments, encoded slashes, backslashes, rooted paths);
- drops client-sent `X-Origin-Auth`, `X-Vand-Client-IP`, `X-Forwarded-*`, `Forwarded`, `X-Real-IP`, `CF-Connecting-IP`,
  `Host`, `Expect` and hop-by-hop headers, then sets `X-Vand-Client-IP` from Vercel's platform-set `x-real-ip`;
- buffers the body (≤ 4,500,000 bytes: the decimal reading of Vercel's 4.5 MB function limit) and returns a JSON 413
  above it; passes redirects and every
  `Set-Cookie` through; marks responses `no-store`; strips `Content-Encoding`/`Content-Length` (bodies are decoded).

Upload ceiling becomes **4 MiB** on Vercel (SPA check via `VERCEL=1` at build, API `VAND_MAX_UPLOAD_BYTES=4194304`).
A 4 MiB file in multipart form data measured ≈ 4.19 MB on the wire, ~300 KB under the gateway ceiling (unit test).

## Consequences
- The secret exists only in Vercel's server-side env (Production scope) and the API's env. It is never a `VITE_*` var.
- Uploads above 4 MB are not possible through Vercel. Raising this needs direct-to-R2 presigned uploads (new design,
  scanning still mandatory) or a different edge — a future decision.
- Vercel's 4.5 MB limit also applies to responses; current API responses are paginated JSON well below it.
- Function invocations count against the Vercel plan's usage. Check the plan/terms the project is on (Hobby is
  intended for non-commercial use).
- Verified: 29 unit tests (proxy + handler), the full 17-step acceptance test and `tests/staging/live_checks.sh`
  through the same gateway code in a local Vercel emulation (`tests/staging/local_gateway.mjs`). **Not yet verified on
  Vercel itself** (no API host exists yet; Vercel docs could not be fetched from the build sandbox — limits were taken
  from Vercel documentation quoted in search results on 2026-11-03).
