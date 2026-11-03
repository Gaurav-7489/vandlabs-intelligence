// LOCAL REHEARSAL ONLY: emulates the Vercel deployment on one port.
//   - serves apps/web/dist with the SPA fallback and the response headers declared in apps/web/vercel.json (incl. CSP)
//   - sends /api/v1/* through the SAME gateway code the Vercel function runs (apps/web/src/edge/proxy.ts)
// The gateway requires an https API origin, so the harness gives it https://api.rehearsal.invalid and maps that one
// host to the local plain-http API inside fetch. Nothing else is rewritten.
//   node --experimental-strip-types tests/staging/local_gateway.mjs
//   env: PORT (5180), API_LOCAL (http://127.0.0.1:8001), ORIGIN_AUTH_SECRET (same as the API's VAND_ORIGIN_AUTH_SECRET)
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { Readable } from "node:stream";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { proxyApi } from "../../apps/web/src/edge/proxy.ts";

const ROOT = fileURLToPath(new URL("../../apps/web/", import.meta.url));
const DIST = join(ROOT, "dist");
const PORT = Number(process.env.PORT ?? 5180);
const API_LOCAL = process.env.API_LOCAL ?? "http://127.0.0.1:8001";
const FAKE_ORIGIN = "https://api.rehearsal.invalid";
const cfg = { apiOrigin: FAKE_ORIGIN, originAuthSecret: process.env.ORIGIN_AUTH_SECRET ?? "" };
const vercel = JSON.parse(await readFile(join(ROOT, "vercel.json"), "utf8"));
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json", ".ico": "image/x-icon", ".woff2": "font/woff2", ".png": "image/png" };

const localFetch = (input, init) => fetch(String(input).replace(FAKE_ORIGIN, API_LOCAL), init);

function vercelHeaders(pathname) {
  const out = {};
  for (const rule of vercel.headers) {
    const re = new RegExp("^" + rule.source.replace(/\(\.\*\)/g, ".*") + "$");
    if (re.test(pathname)) for (const h of rule.headers) out[h.key] = h.value;
  }
  return out;
}

createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  try {
    if (url.pathname.startsWith("/api/")) {
      if (!url.pathname.startsWith("/api/v1/")) { res.writeHead(404).end(); return; }
      const body = ["GET", "HEAD"].includes(req.method) ? undefined : Readable.toWeb(req);
      const request = new Request(url, { method: req.method, headers: req.headers, body, duplex: "half" });
      const r = await proxyApi(request, cfg, req.socket.remoteAddress ?? null, localFetch);
      const headers = {};
      r.headers.forEach((v, k) => { if (k !== "set-cookie") headers[k] = v; });
      const cookies = r.headers.getSetCookie();
      if (cookies.length) headers["set-cookie"] = cookies;
      res.writeHead(r.status, { ...vercelHeaders(url.pathname), ...headers });
      if (r.body) Readable.fromWeb(r.body).pipe(res); else res.end();
      return;
    }
    let file = normalize(join(DIST, url.pathname));
    if (!file.startsWith(DIST) || !(await stat(file).then((s) => s.isFile(), () => false))) file = join(DIST, "index.html");
    const rel = "/" + file.slice(DIST.length + 1);
    res.writeHead(200, { "content-type": TYPES[extname(file)] ?? "application/octet-stream", ...vercelHeaders(rel === "/index.html" ? "/index.html" : url.pathname) });
    res.end(await readFile(file));
  } catch (e) {
    console.error(e);
    if (!res.headersSent) res.writeHead(500).end(); else res.end();
  }
}).listen(PORT, () => console.log(`gateway rehearsal on http://localhost:${PORT} -> ${API_LOCAL}`));
