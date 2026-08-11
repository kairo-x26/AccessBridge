import { expect, test } from "@playwright/test";

import { axe, signIn, USERS } from "./helpers";

test("signed-out visitors are sent to sign in", async ({ page }) => {
  await page.goto("/queue");
  await expect(page).toHaveURL(/\/login\?next=%2Fqueue/);
  await page.getByLabel("Organization").fill("riverbend");
  await page.getByLabel("Email").fill(USERS.coordinator);
  await page.getByLabel("Password").fill("wrong-password-9A");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "incorrect" })).toBeVisible();
});

test("workflow A: a coordinator approves sending a ready package", async ({ page }) => {
  await signIn(page, USERS.coordinator);
  await page.getByRole("tab", { name: "Needs action" }).click();
  await page.getByRole("link", { name: "Luis Moreno" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Luis Moreno" })).toBeVisible();
  const route = page.getByRole("list", { name: "Referral route" });
  await expect(route).toContainText("Agent proposes: Send package to specialist");
  await expect(route).toContainText("Not done yet");

  await route.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("Approved. The agent will carry it out now.")).toBeVisible();
  // The worker sends the package; the page shows the new stop with its receipt as evidence.
  await expect(async () => {
    await page.reload();
    await expect(route.locator('[aria-current="step"]')).toContainText("Sent to specialist", { timeout: 1000 });
  }).toPass({ timeout: 20_000 });
  await expect(route.locator('[aria-current="step"]')).toContainText("Transmission receipt");
});

test("a coordinator reviews a referral package with evidence highlighting", async ({ page }) => {
  await signIn(page, USERS.coordinator);
  await page.getByRole("link", { name: "Grace Okafor" }).click();
  await expect(page.getByRole("heading", { name: "Referral package" })).toBeVisible();
  await page.getByRole("button", { name: /Show in referral-letter\.txt/ }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator("mark")).toBeVisible();
  await dialog.getByRole("button", { name: "Close" }).click();
  expect(await axe(page)).toEqual([]);
});

test("a clinician sees status but no contact details or controls", async ({ page }) => {
  await signIn(page, USERS.clinician);
  await expect(page.getByRole("link", { name: "Approvals" })).toHaveCount(0);
  await page.getByRole("tab", { name: "All" }).click();
  await page.getByRole("link", { name: "James Whitfield" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "James Whitfield" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Patient messages" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Record a change" })).toHaveCount(0);
});

test("key screens have no WCAG 2.2 AA violations", async ({ page }) => {
  await signIn(page, USERS.admin);
  for (const path of ["/queue?view=all", "/approvals", "/tasks?view=all", "/dashboard", "/audit", "/policies", "/admin?tab=organization", "/admin?tab=templates", "/inbox", "/account"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    expect(await axe(page), path).toEqual([]);
  }
});

test("the policy assistant answers from approved procedures with citations", async ({ page }) => {
  await signIn(page, USERS.coordinator);
  await page.goto("/policies");
  await page.getByLabel("Your question").fill("How long before we follow up when the specialist hasn't acknowledged?");
  await page.getByRole("button", { name: "Search procedures" }).click();
  await expect(page.getByText("Quoted from your procedures")).toBeVisible();
  await expect(page.locator("#source-1")).toContainText("Specialty referral procedure");
  await page.getByLabel("Your question").fill("What is the visitor parking policy?");
  await page.getByRole("button", { name: "Search procedures" }).click();
  await expect(page.getByText("Not in your procedures")).toBeVisible();
});

test("an administrator invites a navigator who can then sign in", async ({ page, browser }) => {
  await signIn(page, USERS.admin);
  await page.goto("/admin?tab=people");
  await page.getByLabel("Email").fill("new.navigator@riverbend.example.org");
  await page.getByLabel("Role").first().selectOption("navigator");
  await page.getByRole("button", { name: "Create invitation" }).click();
  const link = (await page.locator("p", { hasText: "/accept-invitation?token=" }).textContent())!.trim();
  const fresh = await browser.newPage();
  await fresh.goto(link);
  await fresh.getByLabel("Your full name").fill("Nia Navigator");
  await fresh.getByLabel("Choose a password").fill("Fresh-Password-2026");
  await fresh.getByLabel("Confirm password").fill("Fresh-Password-2026");
  await fresh.getByRole("button", { name: "Create my account" }).click();
  await expect(fresh.getByRole("heading", { name: "You’re in" })).toBeVisible();
  await fresh.close();
});

test("a security administrator lands on the audit log", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Organization").fill("riverbend");
  await page.getByLabel("Email").fill(USERS.security);
  await page.getByLabel("Password").fill("Demo-Password-2026");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/audit/);
  await expect(page.getByRole("heading", { name: "Audit log" })).toBeVisible();
});
