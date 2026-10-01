/**
 * Browser smoke tests: every route at desktop and 400 px width, no page errors, no horizontal scroll, no serious or
 * critical axe violations (WCAG 2 A/AA). The console runs against a local synthetic lake built by
 * scripts/decisions_demo.py (LAU_E2E_LAKE). Locally the installed Chrome is used with a throwaway profile; CI installs
 * Chromium.
 */
import { defineConfig } from "@playwright/test";

const port = Number(process.env.LAU_E2E_PORT ?? 8791);
const lake = process.env.LAU_E2E_LAKE ?? ".local_lake/decisions_demo";
const env = [
  "LAU_ENV_FILE=/dev/null",
  "LAU_BACKEND=local",
  `LAU_LOCAL_LAKE=${lake}`,
  `LAU_CONFIG_DIR=${lake}/config`,
  `LAU_STATE_DIR=${lake}/state`,
  `LAU_LESSONS_FILE=${lake}/LESSONS.md`,
].join(" ");

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : 4,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    channel: process.env.CI ? undefined : "chrome",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1280, height: 900 } } },
    { name: "narrow", use: { viewport: { width: 400, height: 900 } } },
  ],
  webServer: {
    command: `cd ../.. && ${env} uv run lau console --port ${port}`,
    url: `http://127.0.0.1:${port}/api/status`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
