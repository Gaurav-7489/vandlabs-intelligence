// Browser E2E for management actions: direct low-risk task, document reprocess + two-step delete, invite link, sign-out-everywhere.
import { createRequire } from "node:module";
import assert from "node:assert/strict";
const { chromium } = createRequire(import.meta.url)("playwright");
const BASE = process.env.WEB_URL ?? "http://localhost:5173";
const b = await chromium.launch(); const ctx = await b.newContext({ permissions: ["clipboard-read", "clipboard-write"] }); const page = await ctx.newPage();
const errors = []; page.on("pageerror", (e) => errors.push(String(e)));
const step = (s) => console.log("✓", s);
async function login(email) {
  await page.goto(BASE); await page.getByLabel("Work email").fill(email);
  await page.getByRole("button", { name: "Sign in" }).click(); await page.getByRole("navigation", { name: "Primary" }).waitFor();
}
await login("owner@northwind-demo.example.com");

await page.getByRole("link", { name: "Tasks" }).click();
const title = `Call client ${Date.now()}`;
await page.getByLabel("New low-risk task").fill(title);
await page.getByRole("button", { name: "Add task" }).click();
await page.getByText("Task created.").waitFor();
const row = page.locator("tr", { hasText: title });
await row.getByText("Created directly (not a decision)").waitFor();
step("direct low-risk task created and labelled as not a decision");

await page.getByRole("link", { name: "Knowledge" }).click();
const fname = `ui-${Date.now()}.txt`;
await page.locator('input[type="file"]').setInputFiles({ name: fname, mimeType: "text/plain", buffer: Buffer.from("ui action probe note") });
const drow = page.locator("tr", { hasText: fname });
await drow.getByText(/Completed|Requires review/).waitFor({ timeout: 60000 });
await drow.getByRole("button", { name: "Reprocess" }).click();
await page.getByText(`“${fname}” queued for reprocessing.`).waitFor();
await drow.getByText(/Completed|Requires review/).waitFor({ timeout: 60000 });
step("document reprocessed");
await drow.getByRole("button", { name: `Delete ${fname}` }).click();
await drow.getByRole("button", { name: "Confirm delete" }).waitFor();
await drow.getByRole("button", { name: "Cancel" }).click();
assert.equal(await page.locator("tr", { hasText: fname }).count(), 1, "cancel must not delete");
await drow.getByRole("button", { name: `Delete ${fname}` }).click();
await drow.getByRole("button", { name: "Confirm delete" }).click();
await page.getByText(`“${fname}” deleted with its derived records.`).waitFor();
await page.locator("tr", { hasText: fname }).waitFor({ state: "detached" });
step("two-step delete: cancel keeps the file; confirm removes it");

await page.getByRole("link", { name: "Administration" }).click();
const invitee = `invitee${Date.now()}@northwind-demo.example.com`;
await page.getByLabel("Email", { exact: true }).fill(invitee);
await page.getByRole("button", { name: "Add member" }).click();
await page.getByText("Share this sign-up link").waitFor();
assert.ok((await page.locator("code").innerText()).includes(`invite=1&email=${encodeURIComponent(invitee)}`));
step("invite link shown after adding a member");
await page.getByRole("button", { name: "Sign manager@northwind-demo.example.com out everywhere" }).click();
await page.getByText(/active session|No active sessions/).waitFor();
step("sign-out-everywhere action reports its result (dev auth has no server sessions)");
assert.deepEqual(errors, []);
await b.close(); console.log("UI ACTIONS E2E PASSED");
