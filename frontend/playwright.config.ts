import { defineConfig, devices } from "@playwright/test";

/**
 * Browser tests against a running OmniOSINT instance.
 *
 * They are driven by scripts/dev/run-e2e.sh, which prepares an empty test
 * database, starts the application, passes its address and first-run setup
 * link in OMNIOSINT_E2E_BASE_URL and OMNIOSINT_E2E_SETUP_URL, and stops it
 * afterwards. Run them directly only against a disposable installation: they
 * complete first-run setup and create users.
 */
const baseURL = process.env.OMNIOSINT_E2E_BASE_URL ?? "http://127.0.0.1:8765";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  outputDir: "test-results",
  use: {
    baseURL,
    trace: "off",
    screenshot: "only-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
});
