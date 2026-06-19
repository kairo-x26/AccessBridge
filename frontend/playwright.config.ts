import { defineConfig, devices } from "@playwright/test";

const BACKEND = "http://127.0.0.1:8100";
const e2eDb = "sqlite:///var/e2e.db";

/**
 * End-to-end tests run against a freshly seeded backend and a production build of the
 * frontend, on ports that don't collide with local development servers.
 */
export default defineConfig({
  testDir: "tests/e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://localhost:3100",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command:
        `cd ../backend && rm -f var/e2e.db* && rm -rf var/e2e-docs && ` +
        `AB_DATABASE_URL=${e2eDb} AB_STORAGE_DIR=var/e2e-docs uv run python -m app.seed >/dev/null && ` +
        `(AB_DATABASE_URL=${e2eDb} AB_STORAGE_DIR=var/e2e-docs AB_LOG_LEVEL=WARNING ` +
        `uv run python -m app.workers.run >/dev/null 2>&1 &) && ` +
        `AB_DATABASE_URL=${e2eDb} AB_STORAGE_DIR=var/e2e-docs AB_CORS_ORIGINS='["http://localhost:3100"]' ` +
        `uv run uvicorn app.main:app --port 8100 --log-level warning`,
      url: `${BACKEND}/health`,
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: "pnpm exec next build && pnpm exec next start --port 3100",
      url: "http://localhost:3100/login",
      env: { BACKEND_URL: BACKEND, NEXT_PUBLIC_DEMO: "1" },
      timeout: 300_000,
      reuseExistingServer: false,
    },
  ],
});
