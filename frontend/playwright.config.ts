import { defineConfig, devices } from "@playwright/test";

// The suite drives a real browser against the built image behind nginx, so it
// exercises the whole chain: bundle, SPA fallback, /api proxy, FastAPI and
// Postgres. Point it at the isolated e2e stack, never the development one.
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3100";

export default defineConfig({
  testDir: "./e2e",
  // Imports mutate shared server state, so specs run one at a time and each
  // one works on a test id nobody else touches.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
