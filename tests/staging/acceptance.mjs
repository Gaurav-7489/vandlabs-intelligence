// Staging acceptance test: the full 17-step journey in a real browser against a deployed environment.
//   BASE_URL            e.g. https://vandlabs-intelligence.vercel.app (or http://localhost:5180 for run_local_rehearsal.sh)
//   IDP                 "auth0" (real staging) | "test-issuer" (local rehearsal only - does NOT count as live verification)
//   REQUESTER_EMAIL/PASSWORD, APPROVER_EMAIL/PASSWORD, AUDITOR_EMAIL/PASSWORD   (org A; synthetic users)
//   OUTSIDER_EMAIL/PASSWORD                                                   (member of org B only)
//   EXPECT_SCAN         "clean" in staging (real ClamAV); "not_performed" allowed only in rehearsal
// Never point this at production or use real customer data.
import { createRequire } from "node:module";
import assert from "node:assert/strict";
const { chromium } = createRequire(import.meta.url)("playwright");

const env = (k, d) => process.env[k] ?? d ?? (() => { throw new Error(`missing env ${k}`); })();
const BASE = env("BASE_URL").replace(/\/$/, "");
const IDP = env("IDP", "auth0");
const EXPECT_SCAN = env("EXPECT_SCAN", "clean");
if (IDP === "auth0" && EXPECT_SCAN !== "clean") throw new Error("staging run must require a real clean scan");
const results = [];
const step = (n, s) => { results.push(`${n}. ${s}`); console.log(`✓ ${n}. ${s}`); };

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();
const consoleErrors = []; const serverErrors = [];
page.on("pageerror", (e) => consoleErrors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error" && !/status of 40[134]/.test(m.text())) consoleErrors.push(m.text()); });
page.on("response", (r) => { if (r.url().startsWith(BASE + "/api/") && r.status() >= 500) serverErrors.push(`${r.status()} ${r.url()}`); });

async function idpLogin(email, password) {
  if (IDP === "test-issuer") {
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("MFA").uncheck(); // rehearsal users are non-privileged
    await page.getByRole("button", { name: "Sign in" }).click();
    return;
  }
  // Auth0 Universal Login (identifier-first). Selectors are standard Universal Login fields; adjust if the tenant customizes them.
  await page.locator('input[name="username"]').fill(email);
  const pw = page.locator('input[name="password"]');
  if (!(await pw.isVisible().catch(() => false))) await page.getByRole("button", { name: /continue/i }).click();
  await pw.fill(password);
  await page.getByRole("button", { name: /continue|log in/i }).click();
}
async function signIn(who) {
  await page.goto(BASE);
  await page.getByRole("button", { name: "Continue to sign in" }).click();
  await idpLogin(env(`${who}_EMAIL`), env(`${who}_PASSWORD`, "unused"));
  await page.getByRole("navigation", { name: "Primary" }).waitFor({ timeout: 30000 });
}
async function signOut() {
  // The app ends the server session, then navigates through the IdP end-session endpoint, which redirects back to BASE.
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByRole("button", { name: "Continue to sign in" }).waitFor({ timeout: 30000 });
}
const apiGet = (path, orgId) => page.request.get(`${BASE}/api/v1${path}`, { headers: orgId ? { "X-Org-ID": orgId } : {} });

// 1-2
await signIn("REQUESTER");
step(1, "signed in through the identity provider");
const me = await (await apiGet("/me")).json();
const orgA = me.memberships[0].org_id;
await page.getByText(me.memberships[0].org_name).first().waitFor();
step(2, `entered authorized organization (${me.memberships.length} membership(s))`);

// 3-6
const today = new Date(); const d = (n) => new Date(today.getTime() + n * 864e5).toISOString().slice(0, 10);
const tag = `ACC-${Date.now()}`;
const csv = ["type,id,title,customer,owner,due date,status,depends on",
  `commitment,${tag}-C,Deliver ${tag} rollout,Synthetic Co,Ana Cruz,${d(4)},in progress,${tag}-T`,
  `task,${tag}-T,Finish ${tag} adapter,,Lee Park,${d(-2)},in progress,`].join("\n");
await page.getByRole("link", { name: "Knowledge" }).click();
await page.locator('input[type="file"]').setInputFiles({ name: `${tag}.csv`, mimeType: "text/csv", buffer: Buffer.from(csv) });
await page.getByText(`${tag}.csv`).first().waitFor({ timeout: 30000 });
step(3, "uploaded a synthetic spreadsheet");
const row = page.locator("tr", { hasText: `${tag}.csv` });
const scanText = EXPECT_SCAN === "clean" ? "Scan: Clean" : "Not scanned";
await row.getByText(scanText).waitFor({ timeout: 180000 });
step(4, `scan status shown as "${scanText}"`);
await row.getByText(/Completed|Requires review/).waitFor({ timeout: 180000 });
step(5, "document processed and ingested");
await page.getByRole("link", { name: "Insights" }).click();
const ins = page.getByRole("button", { name: new RegExp(`At risk: Deliver ${tag} rollout`) });
await ins.waitFor({ timeout: 60000 });
await ins.click();
await page.getByText(`Finish ${tag} adapter`).first().waitFor();
step(6, "evidence-backed risk insight generated");

// 7
await page.getByRole("button", { name: "Create decision" }).click();
await page.getByRole("button", { name: "Submit for approval" }).click();
await page.getByText("Awaiting approval").first().waitFor();
const title = await page.getByRole("heading", { level: 1 }).innerText();
const decisionId = page.url().split("/decisions/")[1];
step(7, "decision created and submitted");

// 8-12
await signOut();
await signIn("APPROVER");
step(8, "second authorized user signed in");
await page.getByRole("link", { name: "Decisions" }).click();
await page.getByRole("link", { name: title }).first().click();
await page.getByRole("button", { name: "Approve", exact: true }).click();
await page.getByText("Approved").first().waitFor();
step(9, "decision approved by a different person");
await page.getByRole("button", { name: "Execute approved action" }).click();
await page.getByText("Verified", { exact: true }).waitFor();
step(10, "permitted action executed (server-verified)");
const tasks = await (await apiGet("/tasks?origin=execution&limit=50", orgA)).json();
assert.ok(tasks.items.some((t) => t.decision_id === decisionId), "execution task not found");
step(11, "created task confirmed via API");
await page.getByLabel("Outcome").selectOption("improved");
await page.getByRole("button", { name: "Record outcome" }).click();
await page.getByText("Outcome: improved").waitFor();
step(12, "outcome recorded");

// 13
await signOut();
await signIn("AUDITOR");
const audit = await (await apiGet("/audit?limit=200", orgA)).json();
const acts = new Set(audit.items.filter((e) => e.resource_id === decisionId).map((e) => e.action));
for (const a of ["decision.created", "decision.submitted", "decision.approve", "decision.executed", "decision.outcome_recorded"]) assert.ok(acts.has(a), `audit missing ${a}`);
step(13, "audit history complete for the decision");

// 14
await signOut();
await signIn("OUTSIDER");
const foreign = await apiGet(`/decisions/${decisionId}`, orgA);
assert.equal(foreign.status(), 403, "outsider must be denied org A");
const own = (await (await apiGet("/me")).json()).memberships[0].org_id;
assert.equal((await apiGet(`/decisions/${decisionId}`, own)).status(), 404, "decision id must not resolve in another tenant");
step(14, "cross-organization access denied (403 for foreign org, 404 for foreign id)");

// 15
await page.reload();
await page.getByRole("navigation", { name: "Primary" }).waitFor();
await signOut();
await page.reload();
await page.getByRole("button", { name: "Continue to sign in" }).waitFor();
step(15, "refresh keeps the session; logout ends it and survives refresh");

// 16
await signIn("REQUESTER");
for (const w of [320, 375, 768, 1440]) {
  await page.setViewportSize({ width: w, height: 800 });
  for (const route of ["Insights", "Decisions"]) {
    if (w < 1024) await page.getByRole("button", { name: "Open navigation" }).click();
    await page.getByRole("link", { name: route, exact: true }).click();
    await page.getByRole("heading", { level: 1 }).waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), false, `overflow ${route}@${w}`);
  }
}
step(16, "responsive layouts OK at 320/375/768/1440");

// 17 (browser side; server logs must also be reviewed in the hosting dashboards)
assert.deepEqual(serverErrors, [], `5xx responses: ${serverErrors.join(", ")}`);
assert.deepEqual(consoleErrors, [], `console errors: ${consoleErrors.join(" | ")}`);
step(17, "no 5xx responses and no browser console errors (server logs: check Render dashboards)");

await browser.close();
console.log(`\nACCEPTANCE PASSED (${IDP}${IDP === "test-issuer" ? " - REHEARSAL ONLY, not live verification" : ""})`);
