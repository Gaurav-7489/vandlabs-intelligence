// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import { configError, proxyApi, resolveTarget, type Fetch } from "./proxy";

const cfg = { apiOrigin: "https://api.example.test", originAuthSecret: "s".repeat(40) };
const web = "https://vandlabs-intelligence.vercel.app";

function capture(res: Response = new Response("{}", { status: 200 })) {
  const calls: { url: string; init: RequestInit }[] = [];
  const f: Fetch = vi.fn(async (input, init) => { calls.push({ url: String(input), init: init ?? {} }); return res.clone(); });
  return { f, calls };
}

describe("resolveTarget", () => {
  it("keeps original /api/v1 paths and strips the internal routing param", () => {
    expect(resolveTarget(`${web}/api/v1/insights?limit=20&__vand_path=insights`)).toEqual({ path: "/api/v1/insights", search: "?limit=20" });
  });
  it("rebuilds the path from the rewrite param", () => {
    expect(resolveTarget(`${web}/api/gateway?__vand_path=auth%2Fcallback&code=abc&state=x`)).toEqual({ path: "/api/v1/auth/callback", search: "?code=abc&state=x" });
  });
  it("dot segments are resolved by the URL parser and cannot leave /api/v1", () => {
    expect(resolveTarget(`${web}/api/v1/a/%2e%2e/b`)?.path).toBe("/api/v1/b");
    expect(resolveTarget(`${web}/api/v1/%2e%2e/%2e%2e/healthz`)).toBeNull();
  });
  it.each([
    `${web}/api/gateway`,                                      // missing
    `${web}/api/gateway?__vand_path=a&__vand_path=b`,           // ambiguous
    `${web}/api/gateway?__vand_path=..%2F..%2Fadmin`,           // traversal
    `${web}/api/gateway?__vand_path=docs%2F%252e%252e%2Fx`,     // double-encoded traversal
    `${web}/api/gateway?__vand_path=%2F%2Fevil.test%2Fx`,       // protocol-relative
    `${web}/api/gateway?__vand_path=a%5Cb`,                     // backslash
    `${web}/api/v1/a/%2F/b`,                                    // encoded slash
    `${web}/api/v2/x?__vand_path=x&__vand_path=y`,
  ])("refuses %s", (u) => expect(resolveTarget(u)).toBeNull());
});

describe("configError", () => {
  it.each([
    [{ apiOrigin: "", originAuthSecret: "x".repeat(40) }, "unconfigured"],
    [{ apiOrigin: "https://a.test", originAuthSecret: "short" }, "weak_secret"], // pragma: allowlist secret (test literal)
    [{ apiOrigin: "http://a.test", originAuthSecret: "x".repeat(40) }, "bad_origin"],
    [{ apiOrigin: "https://a.test/prefix", originAuthSecret: "x".repeat(40) }, "bad_origin"],
    [{ apiOrigin: "https://u:p@a.test", originAuthSecret: "x".repeat(40) }, "bad_origin"], // pragma: allowlist secret (fake userinfo)
    [cfg, null],
  ])("%j => %s", (c, want) => expect(configError(c)).toBe(want));
});

describe("proxyApi", () => {
  it("fails closed when unconfigured and never calls upstream", async () => {
    const { f } = capture();
    const res = await proxyApi(new Request(`${web}/api/v1/me`), { apiOrigin: "", originAuthSecret: "" }, "1.2.3.4", f);
    expect(res.status).toBe(503);
    expect(f).not.toHaveBeenCalled();
  });

  it("adds the origin secret server-side and drops client-forged trust headers", async () => {
    const { f, calls } = capture();
    const req = new Request(`${web}/api/v1/me`, { headers: {
      "x-origin-auth": "forged", "x-vand-client-ip": "6.6.6.6", "x-forwarded-for": "6.6.6.6", "cf-connecting-ip": "6.6.6.6",
      "x-real-ip": "6.6.6.6", forwarded: "for=6.6.6.6", "x-forwarded-host": "evil.test", expect: "100-continue", cookie: "__Host-vand_session=abc", "x-csrf-token": "t",
    } });
    await proxyApi(req, cfg, "203.0.113.9", f);
    expect(calls[0].url).toBe("https://api.example.test/api/v1/me");
    const h = new Headers(calls[0].init.headers);
    expect(h.get("x-origin-auth")).toBe(cfg.originAuthSecret);
    expect(h.get("x-vand-client-ip")).toBe("203.0.113.9");
    for (const k of ["x-forwarded-for", "cf-connecting-ip", "x-real-ip", "forwarded", "x-forwarded-host", "host", "expect"]) expect(h.get(k)).toBeNull();
    expect(h.get("cookie")).toBe("__Host-vand_session=abc");
    expect(h.get("x-csrf-token")).toBe("t");
    expect(calls[0].init.redirect).toBe("manual");
  });

  it("forwards bodies for writes", async () => {
    const { f, calls } = capture();
    await proxyApi(new Request(`${web}/api/v1/decisions`, { method: "POST", body: '{"a":1}', headers: { "content-type": "application/json" } }), cfg, null, f);
    expect(calls[0].init.method).toBe("POST");
    expect(await new Response(calls[0].init.body).text()).toBe('{"a":1}');
  });

  it("passes redirects and every Set-Cookie through, never caches, drops stale encoding headers", async () => {
    const up = new Response(null, { status: 302, headers: { location: "https://tenant.auth0.com/authorize?x=1", "content-encoding": "gzip" } });
    up.headers.append("set-cookie", "a=1; Path=/; HttpOnly; Secure");
    up.headers.append("set-cookie", "b=2; Path=/; HttpOnly; Secure");
    const { f } = capture(up);
    const res = await proxyApi(new Request(`${web}/api/v1/auth/login`), cfg, null, f);
    expect(res.status).toBe(302);
    expect(res.headers.get("location")).toContain("auth0.com");
    expect(res.headers.getSetCookie()).toEqual(["a=1; Path=/; HttpOnly; Secure", "b=2; Path=/; HttpOnly; Secure"]);
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(res.headers.get("content-encoding")).toBeNull();
  });

  it("rejects declared oversize bodies with a JSON 413 before contacting the origin", async () => {
    const { f } = capture();
    const req = new Request(`${web}/api/v1/documents`, { method: "POST", body: "x", headers: { "content-length": String(5 * 1024 * 1024) } });
    const res = await proxyApi(req, cfg, null, f);
    expect(res.status).toBe(413);
    expect((await res.json()).error.code).toBe("payload_too_large");
    expect(f).not.toHaveBeenCalled();
  });

  it("rejects undeclared (streamed) oversize bodies too", async () => {
    const { f } = capture();
    const stream = new ReadableStream({ start(c) { c.enqueue(new Uint8Array(600)); c.enqueue(new Uint8Array(600)); c.close(); } });
    const req = new Request(`${web}/api/v1/documents`, { method: "POST", body: stream, duplex: "half" } as RequestInit);
    const res = await proxyApi(req, { ...cfg, maxBodyBytes: 1000 }, null, f);
    expect(res.status).toBe(413);
    expect(f).not.toHaveBeenCalled();
  });

  it("returns a JSON 502 without details when the origin is unreachable", async () => {
    const f: Fetch = async () => { throw new TypeError("connect ECONNREFUSED 10.0.0.1:443"); };
    const res = await proxyApi(new Request(`${web}/api/v1/me`), cfg, null, f);
    expect(res.status).toBe(502);
    expect(await res.text()).not.toContain("10.0.0.1");
  });

  it("refuses unsafe paths without calling upstream", async () => {
    const { f } = capture();
    const res = await proxyApi(new Request(`${web}/api/gateway?__vand_path=..%2Fhealthz`), cfg, null, f);
    expect(res.status).toBe(404);
    expect(f).not.toHaveBeenCalled();
  });
});
