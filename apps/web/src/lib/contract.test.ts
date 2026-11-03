import { readdirSync, readFileSync, statSync } from "node:fs";
import { describe, expect, it } from "vitest";

/** Contract gate: every API path the SPA calls must exist in the backend's exported OpenAPI document (right path, right method). */
const root = process.cwd();
const spec = JSON.parse(readFileSync(`${root}/../../docs/api/openapi.json`, "utf8")) as { paths: Record<string, Record<string, unknown>> };
const norm = (p: string) => p.replace(/\{[^}]+\}/g, "{}");
const specKeys = new Set(Object.entries(spec.paths).flatMap(([p, ms]) => Object.keys(ms).map((m) => `${m.toUpperCase()} ${norm(p.replace(/^\/api\/v1/, ""))}`)));

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => { const p = `${dir}/${f}`; return statSync(p).isDirectory() ? files(p) : /\.(ts|tsx)$/.test(p) && !/\.test\./.test(p) ? [p] : []; });
}

function calls(): { key: string; file: string }[] {
  const out: { key: string; file: string }[] = [];
  for (const f of files(`${root}/src`)) {
    const src = readFileSync(f, "utf8");
    // api<T>("/path"...) / api("/path"...) with optional template literal; method from `method: "X"` in the same call
    for (const m of src.matchAll(/api(?:<[^(]*?>)?\(\s*([`"'])(\/[^`"']*)\1\s*(?:,\s*(\{[^)]*?\}))?\s*\)/gs)) {
      const path = m[2].replace(/\$\{[^}]+\}/g, "{}").replace(/\?.*$/, "");
      const method = /method:\s*"(\w+)"/.exec(m[3] ?? "")?.[1] ?? "GET";
      out.push({ key: `${method} ${norm(path)}`, file: f.replace(root, "") });
    }
  }
  return out;
}

describe("SPA <-> API contract", () => {
  const found = calls();
  it("finds the SPA's API calls", () => { expect(found.length).toBeGreaterThan(20); });
  it.each(found.map((c) => [c.key, c.file]))("%s exists in OpenAPI (%s)", (key) => { expect(specKeys.has(key), `${key} missing from docs/api/openapi.json`).toBe(true); });
});
