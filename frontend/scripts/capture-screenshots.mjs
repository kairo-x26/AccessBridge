// Capture the screenshots used in docs/. Run with the demo stack up:
//   cd frontend && pnpm screenshots
import { chromium } from "@playwright/test";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";
const OUT = new URL("../../docs/images/", import.meta.url).pathname;
const PASSWORD = "Demo-Password-2026";

async function session(browser, email, opts = {}) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, ...opts });
  await page.goto(`${BASE}/login`);
  await page.getByLabel("Organization").fill("riverbend");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/queue**");
  return page;
}

async function shot(page, path, name, { full = false, before } = {}) {
  await page.goto(`${BASE}${path}`);
  await page.waitForLoadState("networkidle");
  if (before) await before(page);
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${OUT}${name}.png`, fullPage: full });
  console.log("saved", name);
}

async function referralId(page, name) {
  await page.goto(`${BASE}/queue?view=all&q=${encodeURIComponent(name)}`);
  await page.waitForLoadState("networkidle");
  const href = await page.getByRole("link", { name }).first().getAttribute("href");
  return href;
}

const browser = await chromium.launch();
try {
  const login = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await shot(login, "/login", "01-sign-in");

  const coord = await session(browser, "priya.coordinator@riverbend.example.org");
  await shot(coord, "/queue?view=all", "02-referral-queue");
  await shot(coord, (await referralId(coord, "Luis Moreno")) ?? "/queue", "03-referral-ready-to-send", { full: true });
  await shot(coord, (await referralId(coord, "Grace Okafor")) ?? "/queue", "04-package-review", { full: true });
  await shot(coord, (await referralId(coord, "Elena Ruiz")) ?? "/queue", "05-completed-route", { full: true });
  await shot(coord, (await referralId(coord, "Samuel Brooks")) ?? "/queue", "06-exception");
  await shot(coord, "/approvals", "07-approvals");
  await shot(coord, "/tasks?view=all", "08-tasks");
  await shot(coord, "/policies", "09-policy-assistant", {
    before: async (p) => {
      await p.getByLabel("Your question").fill("How long before we follow up when the specialist hasn't acknowledged?");
      await p.getByRole("button", { name: "Search procedures" }).click();
      await p.getByText("Quoted from your procedures").waitFor();
    },
  });

  const nav = await session(browser, "grace.navigator@riverbend.example.org");
  await shot(nav, "/inbox", "10-patient-replies");

  const admin = await session(browser, "dana.admin@riverbend.example.org");
  await shot(admin, "/dashboard", "11-dashboard", { full: true });
  await shot(admin, "/admin?tab=organization", "12-admin-automation");
  await shot(admin, "/admin?tab=templates", "13-admin-templates");

  const sec = await session(browser, "ivy.security@riverbend.example.org");
  await shot(sec, "/audit", "14-audit-log");

  const dark = await session(browser, "priya.coordinator@riverbend.example.org", { colorScheme: "dark" });
  await shot(dark, (await referralId(dark, "Luis Moreno")) ?? "/queue", "15-dark-mode");

  const phone = await session(browser, "priya.coordinator@riverbend.example.org", { viewport: { width: 390, height: 844 } });
  await shot(phone, "/queue", "16-phone-queue");
} finally {
  await browser.close();
}
