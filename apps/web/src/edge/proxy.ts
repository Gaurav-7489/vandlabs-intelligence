/**
 * Same-origin API gateway: the browser calls /api/v1/* on the web origin; this code forwards the request to the
 * private FastAPI origin and adds the shared `X-Origin-Auth` secret server-side (never in the browser bundle).
 *
 * Used by the Vercel Edge Function in `apps/web/api/gateway.ts`. Pure + dependency-free so it is unit-tested.
 *
 * Security properties (tested in proxy.test.ts):
 * - Fails closed (503) when unconfigured, when the origin is not https, or outside the allowed deployment env.
 * - Only `/api/v1/...` paths with safe characters are forwarded (no `..`, no `//`, no host switching).
 * - Client-supplied trust headers (x-origin-auth, x-vand-client-ip, forwarded-for family, host) are dropped;
 *   the client IP comes only from the platform-set header passed in by the caller.
 * - Redirects are passed through (OIDC login/callback), never followed; responses are `no-store`.
 */

export interface GatewayConfig {
  /** https origin of the FastAPI service, e.g. https://vand-api-staging.onrender.com */
  apiOrigin: string;
  /** >= 32 chars; must equal VAND_ORIGIN_AUTH_SECRET on the API. */
  originAuthSecret: string;
  /** Requests declaring a larger body get a JSON 413 here instead of a dropped upstream connection. */
  maxBodyBytes?: number;
}

/** Vercel Functions reject request bodies above 4.5 MB; mirror that so the SPA always gets a JSON error. */
export const DEFAULT_MAX_BODY_BYTES = 4.5 * 1024 * 1024;

export type Fetch = (input: Request | string | URL, init?: RequestInit) => Promise<Response>;

const PATH_PARAM = "__vand_path";
const SAFE_PATH = /^\/api\/v1\/[A-Za-z0-9._~\-/%]*$/;

/** Headers a client must never be able to set on the forwarded request, plus hop-by-hop headers. */
const STRIP_REQUEST = [
  "host", "connection", "keep-alive", "expect", "proxy-authorization", "proxy-connection", "te", "trailer", "transfer-encoding", "upgrade",
  "x-origin-auth", "x-vand-client-ip", "cf-connecting-ip", "true-client-ip", "x-real-ip", "x-forwarded-for", "x-forwarded-host",
  "x-forwarded-proto", "x-forwarded-port", "forwarded", "content-length",
];
/** The runtime's fetch transparently decodes the body, so these would be wrong on the re-emitted response. */
const STRIP_RESPONSE = ["content-encoding", "content-length", "transfer-encoding", "connection", "keep-alive"];

export function jsonError(status: number, code: string, message: string): Response {
  return new Response(JSON.stringify({ error: { code, message } }), {
    status, headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

/** Returns the forwarded path (+ query without the internal routing param), or null if the request is not forwardable. */
export function resolveTarget(requestUrl: string): { path: string; search: string } | null {
  const url = new URL(requestUrl);
  const params = url.searchParams;
  const routed = params.getAll(PATH_PARAM);
  params.delete(PATH_PARAM);
  let path: string;
  if (url.pathname.startsWith("/api/v1/")) {
    if (routed.length > 1) return null;
    path = url.pathname;
  } else {
    if (routed.length !== 1 || routed[0].startsWith("/")) return null; // ambiguous, missing or rooted => refuse
    path = "/api/v1/" + routed[0];
  }
  if (!SAFE_PATH.test(path) || path.includes("//")) return null;
  const segments = path.split("/").map((s) => { try { return decodeURIComponent(s); } catch { return "\u0000"; } });
  if (segments.some((s) => s === "." || s === ".." || s.includes("/") || s.includes("\\") || s.includes("\u0000"))) return null;
  const search = params.toString();
  return { path, search: search ? `?${search}` : "" };
}

export function configError(cfg: GatewayConfig): string | null {
  if (!cfg.apiOrigin || !cfg.originAuthSecret) return "unconfigured";
  if (cfg.originAuthSecret.length < 32) return "weak_secret";
  let u: URL;
  try { u = new URL(cfg.apiOrigin); } catch { return "bad_origin"; }
  if (u.protocol !== "https:" || u.pathname.replace(/\/+$/, "") !== "" || u.search || u.username || u.password) return "bad_origin";
  return null;
}

async function readBounded(request: Request, limit: number): Promise<Uint8Array | null> {
  if (!request.body) return new Uint8Array(0);
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > limit) { await reader.cancel().catch(() => undefined); return null; }
    chunks.push(value);
  }
  const out = new Uint8Array(total);
  let off = 0;
  for (const c of chunks) { out.set(c, off); off += c.byteLength; }
  return out;
}

export async function proxyApi(request: Request, cfg: GatewayConfig, clientIp: string | null, fetchImpl: Fetch = fetch): Promise<Response> {
  const problem = configError(cfg);
  if (problem) return jsonError(503, "gateway_unavailable", "The API is not available on this deployment.");
  const target = resolveTarget(request.url);
  if (!target) return jsonError(404, "not_found", "Not found");

  const declared = Number(request.headers.get("content-length") ?? "0");
  if (declared > (cfg.maxBodyBytes ?? DEFAULT_MAX_BODY_BYTES)) return jsonError(413, "payload_too_large", "Request too large");

  const headers = new Headers(request.headers);
  for (const h of STRIP_REQUEST) headers.delete(h);
  headers.set("x-origin-auth", cfg.originAuthSecret);
  headers.set("x-vand-client-ip", (clientIp ?? "").split(",")[0].trim());

  const init: RequestInit = { method: request.method, headers, redirect: "manual" };
  if (!["GET", "HEAD"].includes(request.method)) {
    // Buffer (bounded by maxBodyBytes) and send with a fixed length: the API may answer early (401/403/413) and close,
    // which a half-duplex stream turns into a failed fetch; a buffered body keeps the API's real status.
    const limit = cfg.maxBodyBytes ?? DEFAULT_MAX_BODY_BYTES;
    const body = await readBounded(request, limit);
    if (body === null) return jsonError(413, "payload_too_large", "Request too large");
    init.body = body;
  }

  let res: Response;
  try {
    res = await fetchImpl(new URL(target.path + target.search, cfg.apiOrigin).toString(), init);
  } catch {
    return jsonError(502, "upstream_unavailable", "The API is temporarily unreachable. Please retry.");
  }
  const out = new Headers(res.headers);
  for (const h of STRIP_RESPONSE) out.delete(h);
  out.set("cache-control", "no-store");
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers: out });
}
