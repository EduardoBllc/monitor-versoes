import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  // Cada teste sobe o próprio cenário e daemon: montar o git leva segundos.
  timeout: 120_000,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? "list" : "line",
  use: { trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
