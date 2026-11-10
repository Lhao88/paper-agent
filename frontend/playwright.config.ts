import { defineConfig } from "@playwright/test";

const prefix = (process.env.E2E_PROJECT_PREFIX ||= `[e2e-${Date.now()}]`);
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 60000,
  use: { baseURL: "http://127.0.0.1:15173", trace: "retain-on-failure" },
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
      metadata: { projectPrefix: prefix },
    },
  ],
  webServer: [
    {
      command:
        "powershell -NoProfile -ExecutionPolicy Bypass -File ../scripts/uv.ps1 run --offline --locked --directory ../backend python -m app.e2e_server",
      url: "http://127.0.0.1:18010/api/health/ready",
      timeout: 60000,
      reuseExistingServer: false,
      env: { E2E_PROJECT_PREFIX: prefix, E2E_API_PORT: "18010" },
    },
    {
      command: "npm run dev -- --port 15173 --strictPort",
      url: "http://127.0.0.1:15173",
      reuseExistingServer: false,
      env: { API_PROXY_TARGET: "http://127.0.0.1:18010" },
    },
  ],
});
