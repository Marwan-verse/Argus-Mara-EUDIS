import { test, expect } from "@playwright/test";

const origin = "http://127.0.0.1:8082";
const secret = "synthetic-browser-password-42";
async function login(page, username = "testadmin") {
  await page.goto(`${origin}/admin/`);
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page.getByLabel("Password", { exact: true }).fill(secret);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
}
async function confirm(page) {
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Confirm change", exact: true }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
}

test("admin cookie is HttpOnly, nonadmins are refused and state is not stored in browser storage", async ({ page, context }) => {
  await login(page, "testoperator");
  await expect(page.getByRole("alert")).toContainText("Administrator access required");
  await expect(page.getByRole("heading", { name: "Team accounts" })).toHaveCount(0);
  await login(page);
  await expect(page.getByRole("heading", { name: "Team accounts" })).toBeVisible();
  const cookies = await context.cookies();
  expect(cookies.find((cookie) => cookie.name === "argus_admin_dev")).toMatchObject({ httpOnly: true, sameSite: "Strict" });
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length, cookie: document.cookie }))).toEqual({ local: 0, session: 0, cookie: "" });
  const denied = await page.evaluate(async () => (await fetch("/admin/api/groups/forged", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ permissions: ["chat"] }) })).status);
  expect(denied).toBe(403);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Team accounts" })).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Sign in to administration" })).toBeVisible();
});

test("review registration, reset password, revoke sign-ins, ban and reinstate with confirmation", async ({ page, request }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await login(page);
  await page.getByRole("button", { name: "Manage applicant", exact: true }).click();
  await expect(page.getByRole("button", { name: "Approve registration" })).toBeDisabled();
  await page.getByRole("checkbox", { name: "analyst", exact: false }).check();
  await page.getByRole("button", { name: "Approve registration" }).click();
  await expect(page.getByRole("dialog")).toContainText("analyst");
  await confirm(page);
  await expect(page.getByRole("status")).toHaveText("Account saved.");
  let signin = await request.post(`${origin}/v1/login`, { data: { username: "applicant", password: secret } });
  expect(signin.status()).toBe(200);
  const token = (await signin.json()).token;
  await page.getByRole("button", { name: "Manage applicant", exact: true }).click();
  await page.getByRole("button", { name: "Revoke all sign-ins" }).click();
  await confirm(page);
  await expect(page.getByRole("status")).toHaveText("All sign-ins revoked.");
  expect((await request.get(`${origin}/v1/me`, { headers: { Authorization: `Bearer ${token}` } })).status()).toBe(401);
  await page.getByRole("button", { name: "Ban account", exact: true }).click();
  await page.getByRole("button", { name: "Cancel", exact: true }).last().click();
  await expect(page.getByRole("heading", { name: "Manage applicant" })).toBeVisible();
  await page.getByRole("button", { name: "Ban account", exact: true }).click();
  await confirm(page);
  await expect(page.getByRole("status")).toContainText("Account banned");
  signin = await request.post(`${origin}/v1/login`, { data: { username: "applicant", password: secret } });
  expect(signin.status()).toBe(401);
  await page.getByRole("button", { name: "Manage applicant", exact: true }).click();
  await page.getByRole("button", { name: "Reinstate account", exact: true }).click();
  await confirm(page);
  await expect(page.getByRole("status")).toHaveText("Account reinstated.");
  await page.getByRole("button", { name: "Manage applicant", exact: true }).click();
  await page.getByLabel("New password (optional)").fill("replacement-browser-password-42");
  await page.getByRole("button", { name: "Save account", exact: true }).click();
  await confirm(page);
  await expect(page.getByRole("status")).toHaveText("Account saved.");
  expect((await request.post(`${origin}/v1/login`, { data: { username: "applicant", password: secret } })).status()).toBe(401);
  expect((await request.post(`${origin}/v1/login`, { data: { username: "applicant", password: "replacement-browser-password-42" } })).status()).toBe(200);
  await page.getByRole("button", { name: "Audit log", exact: true }).click();
  await expect(page.locator("tbody")).toContainText("user.revoke_sessions");
  await expect(page.locator("tbody")).not.toContainText("replacement-browser-password-42");
  expect(errors).toEqual([]);
});

test("permission matrix, custom group lifecycle and responsive layout", async ({ page }) => {
  await login(page);
  await page.getByRole("button", { name: "Groups & permissions", exact: true }).click();
  await expect(page.getByRole("table")).toContainText("evidence.share");
  await expect(page.getByRole("table")).toContainText("response-coordinator");
  await page.getByRole("button", { name: "Create group", exact: true }).click();
  await page.getByLabel("Group name", { exact: true }).fill("research-team");
  expect(await page.getByLabel("Group name", { exact: true }).evaluate((input) => input.validationMessage)).toBe("");
  await page.getByRole("checkbox", { name: "View map", exact: false }).check();
  await page.getByRole("button", { name: "Save group", exact: true }).click();
  await confirm(page);
  await expect(page.getByRole("status")).toHaveText("Group saved.");
  await page.getByRole("button", { name: "Edit group research-team", exact: true }).click();
  await page.getByRole("button", { name: "Delete group", exact: true }).click();
  await confirm(page);
  await expect(page.getByRole("status")).toHaveText("Group deleted.");
  await page.getByRole("button", { name: "Edit group intelligence", exact: true }).click();
  await expect(page.getByRole("button", { name: "Delete group", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({ path: "test-results/admin-permissions.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "test-results/admin-mobile.png", fullPage: true });
});
