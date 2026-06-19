import path from "node:path";

import { expect, type Page } from "@playwright/test";

export const PASSWORD = "Demo-Password-2026";
export const USERS = {
  coordinator: "priya.coordinator@riverbend.example.org",
  navigator: "grace.navigator@riverbend.example.org",
  admin: "dana.admin@riverbend.example.org",
  clinician: "amara.clinician@riverbend.example.org",
  security: "ivy.security@riverbend.example.org",
};

export async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Organization").fill("riverbend");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/queue/);
}

const axePath = path.join(process.cwd(), "node_modules", "axe-core", "axe.min.js");

/** WCAG 2.2 A/AA violations on the current page (color contrast included). */
export async function axe(page: Page): Promise<string[]> {
  await page.addScriptTag({ path: axePath });
  return page.evaluate(async () => {
    // @ts-expect-error injected global
    const r = await window.axe.run(document, { runOnly: ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"] });
    return r.violations.map(
      (v: { id: string; nodes: { target: string[] }[] }) => `${v.id} → ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(", ")}`,
    );
  });
}
