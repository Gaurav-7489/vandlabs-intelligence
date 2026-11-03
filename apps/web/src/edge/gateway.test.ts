// @vitest-environment node
// Tests for the Vercel handler in apps/web/api/gateway.ts (kept outside /api: every file there becomes a Vercel Function).
import { afterEach, describe, expect, it, vi } from "vitest";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { ModuleKind, ScriptTarget, transpileModule } from "typescript";
import gateway from "../../api/gateway";
import { DEFAULT_MAX_BODY_BYTES } from "./proxy";

const web = "https://vandlabs-intelligence.vercel.app";
const SECRET = "s".repeat(40);

function setEnv(vars: Record<string, string | undefined>) {
  for (const [k, v] of Object.entries(vars)) vi.stubEnv(k, v as string);
}

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

describe("api/gateway.ts", () => {
  it("loads the compiled gateway in Node ESM and fails closed without backend configuration", () => {
    const root = mkdtempSync(join(tmpdir(), "vand-gateway-esm-"));
    try {
      mkdirSync(join(root, "api"), { recursive: true });
      mkdirSync(join(root, "src", "edge"), { recursive: true });
      writeFileSync(join(root, "package.json"), JSON.stringify({ type: "module" }));
      for (const [source, target] of [["../../api/gateway.ts", "api/gateway.js"], ["./proxy.ts", "src/edge/proxy.js"]]) {
        const code = readFileSync(new URL(source, import.meta.url), "utf8");
        writeFileSync(join(root, target), transpileModule(code, {
          compilerOptions: { module: ModuleKind.ESNext, target: ScriptTarget.ES2022 },
        }).outputText);
      }
      const entry = pathToFileURL(join(root, "api", "gateway.js")).href;
      const result = spawnSync(process.execPath, ["--input-type=module", "-e", `
        const { default: gateway } = await import(${JSON.stringify(entry)});
        const response = await gateway.fetch(new Request("https://web.example/api/v1/auth/config"));
        const body = await response.json();
        if (response.status !== 503 || body.error?.code !== "gateway_unavailable") process.exit(1);
        console.log(body.error.code);
      `], {
        encoding: "utf8",
        timeout: 10_000,
        env: { ...process.env, VERCEL_ENV: "production", VAND_API_ORIGIN: "", VAND_ORIGIN_AUTH_SECRET: "" },
      });
      expect(result.status, result.stderr).toBe(0);
      expect(result.stdout).toContain("gateway_unavailable");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("refuses on preview deployments even when configured", async () => {
    setEnv({ VERCEL_ENV: "preview", VAND_API_ORIGIN: "https://api.example.test", VAND_ORIGIN_AUTH_SECRET: SECRET });
    const f = vi.fn(); vi.stubGlobal("fetch", f);
    const res = await gateway.fetch(new Request(`${web}/api/v1/auth/session`));
    expect(res.status).toBe(503);
    expect(f).not.toHaveBeenCalled();
  });

  it("refuses in production when unconfigured", async () => {
    setEnv({ VERCEL_ENV: "production", VAND_API_ORIGIN: "", VAND_ORIGIN_AUTH_SECRET: "" });
    expect((await gateway.fetch(new Request(`${web}/api/v1/auth/session`))).status).toBe(503);
  });

  it("forwards in production with the secret and the platform client IP", async () => {
    setEnv({ VERCEL_ENV: "production", VAND_API_ORIGIN: "https://api.example.test", VAND_ORIGIN_AUTH_SECRET: SECRET });
    const f = vi.fn(async () => new Response('{"authenticated":false}', { status: 200 }));
    vi.stubGlobal("fetch", f);
    const res = await gateway.fetch(new Request(`${web}/api/gateway?__vand_path=auth%2Fsession`, { headers: { "x-real-ip": "198.51.100.7" } }));
    expect(res.status).toBe(200);
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://api.example.test/api/v1/auth/session");
    const h = new Headers(init.headers);
    expect(h.get("x-origin-auth")).toBe(SECRET);
    expect(h.get("x-vand-client-ip")).toBe("198.51.100.7");
  });

  it("a 4 MiB file in multipart form data fits under the gateway/Vercel body ceiling", async () => {
    setEnv({ VERCEL_ENV: "production", VAND_API_ORIGIN: "https://api.example.test", VAND_ORIGIN_AUTH_SECRET: SECRET });
    let forwarded = 0;
    vi.stubGlobal("fetch", vi.fn(async (_u: string, init: RequestInit) => { forwarded = (init.body as Uint8Array).byteLength; return new Response("{}", { status: 201 }); }));
    const form = new FormData();
    form.append("file", new Blob([new Uint8Array(4 * 1024 * 1024)]), "a-rather-long-synthetic-file-name-for-overhead.xlsx");
    const req = new Request(`${web}/api/v1/documents`, { method: "POST", body: form });
    const res = await gateway.fetch(req);
    expect(res.status).toBe(201);
    expect(forwarded).toBeGreaterThan(4 * 1024 * 1024);
    expect(forwarded).toBeLessThan(DEFAULT_MAX_BODY_BYTES);
    expect(DEFAULT_MAX_BODY_BYTES - forwarded).toBeGreaterThan(250_000); // headroom for multipart framing
  });
});
