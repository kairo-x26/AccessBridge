import axe from "axe-core";

/** Run axe on a rendered container; returns violations as readable strings. */
export async function a11yViolations(container: HTMLElement): Promise<string[]> {
  const result = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } }, // jsdom can't compute styles; checked in e2e
  });
  return result.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.length})`);
}
