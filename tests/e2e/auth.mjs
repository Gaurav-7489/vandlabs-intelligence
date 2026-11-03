// Browser E2E for the real OIDC (BFF) flow. Run tests/e2e/run_oidc_stack.sh first and seed the e2e org (see docs).
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
import assert from "node:assert/strict";

const BASE = "http://localhost:5174";
const browser = await chromium.launch();
const ctx = await browser.newContext();
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
const step = (s) => console.log("✓", s);

async function idpLogin(email, mfa) {
  await page.getByLabel("Email").fill(email);
  if (!mfa) await page.getByLabel("MFA").uncheck();
  await page.getByRole("button", { name: "Sign in" }).click();
}

await page.goto(BASE);
await page.getByRole("button", { name: "Continue to sign in" }).waitFor();
step("anonymous visitor sees SSO login, no dev form");
assert.equal(await page.getByLabel("Work email").count(), 0);

await page.getByRole("button", { name: "Continue to sign in" }).click();
await idpLogin("owner@e2e.example.com", true);
await page.getByRole("navigation", { name: "Primary" }).waitFor();
step("OIDC sign-in (PKCE) lands in the app");

const cookies = await ctx.cookies(BASE);
const sess = cookies.find((c) => c.name === "vand_session");
assert.ok(sess && sess.httpOnly && sess.sameSite === "Lax", "session cookie must be HttpOnly + SameSite=Lax");
assert.equal(await page.evaluate(() => document.cookie.includes("vand_session")), false, "JS must not see the session cookie");
const stored = await page.evaluate(() => JSON.stringify({ l: { ...localStorage }, s: { ...sessionStorage } }));
assert.ok(!/eyJ|token|secret/i.test(stored), "no tokens in web storage");
step("session cookie is HttpOnly/Lax; no tokens in JS-visible storage");

await page.reload();
await page.getByRole("navigation", { name: "Primary" }).waitFor();
step("browser refresh restores the session (no re-login)");

await page.getByRole("link", { name: "Administration" }).click();
await page.getByText("staff@e2e.example.com").waitFor();
step("CSRF-protected write path usable: invite a member");
await page.getByLabel("Email", { exact: true }).fill(`new${Date.now()}@e2e.example.com`);
await page.getByRole("button", { name: "Add member" }).click();
await page.getByText("Member added.").waitFor();

await page.getByRole("button", { name: "Sign out" }).click();
await page.waitForURL(/localhost:9000\/logout|localhost:5174/, { timeout: 10000 }).catch(() => {});
await page.goto(BASE);
await page.getByRole("button", { name: "Continue to sign in" }).waitFor();
step("sign-out ends the server session; refresh stays signed out");

// MFA gate: owner without MFA must be stopped by the server
await page.getByRole("button", { name: "Continue to sign in" }).click();
await idpLogin("owner@e2e.example.com", false);
await page.getByText("Multi-factor authentication required").first().waitFor();
step("privileged user without MFA gets the MFA-required screen");
await page.getByRole("button", { name: "Sign out" }).click();

// staff (non-privileged) does not need MFA
await page.goto(BASE);
await page.getByRole("button", { name: "Continue to sign in" }).click();
await idpLogin("staff@e2e.example.com", false);
await page.getByRole("navigation", { name: "Primary" }).waitFor();
assert.equal(await page.getByRole("link", { name: "Administration" }).count(), 0);
step("staff signs in without MFA and sees no admin navigation");

assert.deepEqual(errors, []);
await browser.close();
console.log("AUTH E2E PASSED");
