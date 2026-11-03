import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(`${process.cwd()}/src/styles/index.css`, "utf8");

function tokens(block: RegExp): Record<string, string> {
  const m = css.match(block);
  if (!m) throw new Error("token block not found");
  return Object.fromEntries([...m[1].matchAll(/--([\w-]+):\s*(#[0-9A-Fa-f]{6})/g)].map((x) => [x[1], x[2]]));
}
const lum = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const ratio = (a: string, b: string) => { const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); };

const PAIRS: [string, string][] = [["ink", "canvas"], ["ink", "surface"], ["ink-2", "canvas"], ["ink-2", "surface"], ["ink-2", "muted"], ["ink-3", "canvas"], ["ink-3", "surface"],
  ["ink-3", "muted"], ["accent", "canvas"], ["accent", "surface"], ["accent-ink", "accent"], ["accent", "accent-soft"], ["danger", "danger-soft"], ["warn", "warn-soft"], ["ok", "ok-soft"], ["danger", "surface"]];

describe.each([["light", /:root, :root\[data-theme="light"\] \{([^}]*)\}/], ["dark", /:root\[data-theme="dark"\] \{([^}]*)\}/]] as const)("%s theme contrast (WCAG AA 4.5:1)", (_n, re) => {
  const t = tokens(re);
  it.each(PAIRS)("%s on %s", (fg, bg) => { expect(ratio(t[fg], t[bg])).toBeGreaterThanOrEqual(4.5); });
});
