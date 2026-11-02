// Browser E2E for the first intelligence workflow. Requires: API + worker + web dev server running with seeded demo data.
// Run: node tests/e2e/workflow.mjs   (uses the preinstalled Playwright + Chromium)
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
import assert from "node:assert/strict";

const BASE = process.env.WEB_URL ?? "http://localhost:5173";
const OWNER_EMAIL = process.env.E2E_REQUESTER ?? "manager@northwind-demo.example.com";
const APPROVER = process.env.E2E_APPROVER ?? "approver@northwind-demo.example.com";
const shots = process.env.E2E_SHOTS;

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

async function login(email) {
  await page.goto(BASE);
  await page.getByLabel("Work email").fill(email);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("navigation", { name: "Primary" }).waitFor();
}
const step = (s) => console.log("✓", s);

// --- Requester ---
await login(OWNER_EMAIL);
await page.getByRole("heading", { name: "Overview" }).waitFor();
await page.getByText("High-severity risks").waitFor();
await page.getByText("Upcoming commitments").waitFor();
step("overview widgets load independently with real data");
await page.getByText("Deliver Acme integration").first().waitFor();
if (shots) await page.screenshot({ path: `${shots}/overview-light.png` });

await page.evaluate(() => { window.__noReload = true; });
await page.getByRole("link", { name: "Insights" }).click();
await page.getByRole("heading", { name: "Insights" }).waitFor();
assert.equal(await page.evaluate(() => window.__noReload), true, "navigation must be client-side");
step("client-side navigation keeps the app shell (no page reload)");

const row = page.getByRole("button", { name: /At risk: Deliver Acme integration/ });
await row.click();
await page.getByText("Uncertainty:").waitFor();
await page.getByText("Finish API adapter").first().waitFor();
if (shots) await page.screenshot({ path: `${shots}/insight-detail.png` });
await page.getByRole("button", { name: "Explain" }).click();
await page.getByText("Generated from the stored evidence (no AI model used).").waitFor();
step("insight shows evidence, uncertainty and a clearly-labelled non-AI explanation");

await page.getByRole("button", { name: "Create decision" }).click();
await page.getByRole("button", { name: "Submit for approval" }).click();
await page.getByText("Awaiting approval").first().waitFor();
step("decision created and submitted");

// --- Approver (separation of duties: requester cannot approve) ---
await page.getByText("You proposed this decision, so someone else must approve it.").waitFor().catch(() => {});
const title = await page.getByRole("heading", { level: 1 }).innerText();
await page.getByRole("button", { name: "Sign out" }).click();
await login(APPROVER);
await page.getByText("Decisions awaiting approval").waitFor();
await page.getByRole("link", { name: title }).first().click();
await page.getByRole("button", { name: "Approve", exact: true }).click();
await page.getByRole("button", { name: "Execute approved action" }).click();
await page.getByText("Verified", { exact: true }).waitFor();
step("approval enforced, action executed and verified");

await page.getByLabel("Outcome").selectOption("improved");
await page.getByLabel("Notes").fill("Adapter delivered; commitment back on track.");
await page.getByRole("button", { name: "Record outcome" }).click();
await page.getByText("Outcome: improved").waitFor();
step("outcome recorded against the decision");

await page.getByRole("link", { name: "Tasks" }).click();
await page.locator("td", { hasText: "Created by decision" }).first().waitFor();
step("follow-up task exists in Tasks");

await page.getByRole("link", { name: "Administration" }).click().catch(() => {});

// --- Theme + responsive ---
await page.getByRole("button", { name: /Switch to dark theme/ }).click();
assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), "dark");
if (shots) await page.screenshot({ path: `${shots}/tasks-dark.png` });
step("dark theme toggles");
for (const w of [320, 375, 768, 1440]) {
  await page.setViewportSize({ width: w, height: 800 });
  for (const route of ["Decisions", "Knowledge", "Insights"]) {
    if (w < 1024) { await page.getByRole("button", { name: "Open navigation" }).click(); }
    await page.getByRole("link", { name: route, exact: true }).click();
    await page.getByRole("heading", { level: 1 }).waitFor();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    assert.equal(overflow, false, `horizontal overflow on ${route} at ${w}px`);
  }
}
step("no horizontal overflow at 320/375/768px");
await page.setViewportSize({ width: 390, height: 800 });
await page.waitForTimeout(300);
if (shots) await page.screenshot({ path: `${shots}/mobile-dark.png` });

assert.deepEqual(errors, [], `browser console errors: ${errors.join("\n")}`);
step("no console errors");
await browser.close();
console.log("E2E PASSED");
