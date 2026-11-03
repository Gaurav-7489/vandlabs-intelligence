/** Edge Worker: serves the SPA (static assets, SPA fallback) and proxies /api/* to the origin with a shared secret.
 *  Authenticated API responses are never cached at the edge. Deploy with `wrangler deploy`; configure secrets via `wrangler secret put`. */
interface Env { ASSETS: { fetch: (r: Request) => Promise<Response> }; API_ORIGIN: string; ORIGIN_AUTH_SECRET: string }

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/api/")) return env.ASSETS.fetch(request);
    const target = new URL(url.pathname + url.search, env.API_ORIGIN);
    const headers = new Headers(request.headers);
    headers.set("X-Origin-Auth", env.ORIGIN_AUTH_SECRET);
    // Client IP from Cloudflare's edge header on the INCOMING request; the API trusts it only with a valid X-Origin-Auth.
    headers.set("X-Vand-Client-IP", request.headers.get("cf-connecting-ip") ?? "");
    headers.delete("host"); // let fetch derive Host from the origin URL
    headers.delete("x-forwarded-host");
    const res = await fetch(target, { method: request.method, headers, body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body, redirect: "manual" });
    const out = new Headers(res.headers);
    out.set("Cache-Control", "no-store");
    return new Response(res.body, { status: res.status, statusText: res.statusText, headers: out });
  },
};
