// Malware-scanning checks against a deployed (or rehearsal) environment. Synthetic files only. Part of the A9 run.
//   BASE_URL, IDP ("auth0" | "test-issuer"), REQUESTER_EMAIL / REQUESTER_PASSWORD   (same meaning as acceptance.mjs)
//   OUTAGE=1   also run the outage check: upload while the scanner is SUSPENDED, then wait for the operator (or the
//              rehearsal harness) to RESUME it; the worker must release the held upload by itself (clamd PING).
//   OUTAGE_WAIT_S (default 900)  how long to wait for the held upload to be processed after it was held.
// Checks: (1) EICAR => quarantined, scan "infected", 0 chunks, not searchable; (2) [OUTAGE] scanner down => scan_pending
// + unindexed, never "clean"; after resume => clean + indexed without any manual reprocess.
import { createRequire } from "node:module";
import assert from "node:assert/strict";
const { chromium } = createRequire(import.meta.url)("playwright");

const env = (k, d) => process.env[k] ?? d ?? (() => { throw new Error(`missing env ${k}`); })();
const BASE = env("BASE_URL").replace(/\/$/, "");
const IDP = env("IDP", "auth0");
const OUTAGE = env("OUTAGE", "0") === "1";
const OUTAGE_WAIT_S = Number(env("OUTAGE_WAIT_S", "900"));
const EICAR = "X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*";

const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
await page.goto(BASE);
await page.getByRole("button", { name: "Continue to sign in" }).click();
if (IDP === "test-issuer") {
  await page.getByLabel("Email").fill(env("REQUESTER_EMAIL"));
  await page.getByLabel("MFA").uncheck();
  await page.getByRole("button", { name: "Sign in" }).click();
} else {
  await page.locator('input[name="username"]').fill(env("REQUESTER_EMAIL"));
  const pw = page.locator('input[name="password"]');
  if (!(await pw.isVisible().catch(() => false))) await page.getByRole("button", { name: /continue/i }).click();
  await pw.fill(env("REQUESTER_PASSWORD"));
  await page.getByRole("button", { name: /continue|log in/i }).click();
}
await page.getByRole("navigation", { name: "Primary" }).waitFor({ timeout: 60000 });

const session = await (await page.request.get(`${BASE}/api/v1/auth/session`)).json();
const me = await (await page.request.get(`${BASE}/api/v1/me`)).json();
const org = me.memberships[0].org_id;
const H = { "X-Org-ID": org, "X-CSRF-Token": session.csrf, Origin: BASE };
const upload = async (name, body, mimeType = "text/plain") => {
  const r = await page.request.post(`${BASE}/api/v1/documents`, { headers: H, multipart: { file: { name, mimeType, buffer: Buffer.from(body) } } });
  assert.equal(r.status(), 202, `upload ${name}: ${r.status()} ${await r.text()}`);
  return (await r.json()).id;
};
const doc = async (id) => (await page.request.get(`${BASE}/api/v1/documents/${id}`, { headers: { "X-Org-ID": org } })).json();
const search = async (q) => (await (await page.request.get(`${BASE}/api/v1/search?q=${encodeURIComponent(q)}`, { headers: { "X-Org-ID": org } })).json()).items;
const until = async (id, pred, seconds) => {
  for (let i = 0; i < seconds; i++) { const d = await doc(id); if (pred(d)) return d; await page.waitForTimeout(1000); }
  return doc(id);
};
const tag = `SCAN-${Date.now()}`;

// 1. EICAR is quarantined and never reaches the knowledge base. The file must be EXACTLY the 68-byte EICAR string
//    (scanners only match it with nothing but optional whitespace after it).
const bad = await upload(`${tag}-eicar.txt`, EICAR);
const b = await until(bad, (d) => !["queued", "processing", "scan_pending"].includes(d.status), 300);
assert.equal(b.status, "quarantined", JSON.stringify(b));
assert.equal(b.scan_status, "infected");
assert.equal(b.chunk_count ?? 0, 0, "quarantined file has indexed chunks");
assert.equal((await search("EICAR-STANDARD-ANTIVIRUS-TEST-FILE")).filter((x) => x.document_id === bad).length, 0, "quarantined content is searchable");
console.log(`✓ EICAR quarantined (scan_status=${b.scan_status}), not searchable`);

if (OUTAGE) {
  console.log(">>> SUSPEND the scanner now (Render: suspend vand-clamav-staging). Waiting until uploads are held…");
  let held = null;
  for (let i = 0; i < 60 && !held; i++) {
    const id = await upload(`${tag}-held-${i}.txt`, `${tag} held probe ${i}`);
    const d = await until(id, (x) => x.status !== "queued" && x.status !== "processing", 120);
    if (d.status === "scan_pending") held = { id, d };
    else await page.waitForTimeout(10000); // scanner still answering; try again
  }
  assert.ok(held, "upload never entered scan_pending (is the scanner suspended?)");
  assert.notEqual(held.d.scan_status, "clean");
  assert.equal(held.d.chunk_count ?? 0, 0);
  console.log(`✓ scanner down => held: status=${held.d.status} scan_status=${held.d.scan_status}, unindexed`);
  console.log(">>> RESUME the scanner now. The worker PINGs clamd and releases held uploads by itself (no reprocess click).");
  const r = await until(held.id, (x) => x.scan_status === "clean" && x.status !== "scan_pending", OUTAGE_WAIT_S);
  assert.equal(r.scan_status, "clean", `held upload not processed within ${OUTAGE_WAIT_S}s: ${JSON.stringify(r)}`);
  console.log(`✓ after resume => processed automatically: status=${r.status} scan_status=${r.scan_status}`);
}
await browser.close();
console.log("SCANNER CHECKS PASSED" + (IDP === "test-issuer" ? " (test-issuer - REHEARSAL ONLY)" : ""));
