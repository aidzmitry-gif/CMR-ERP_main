import { defineConfig, devices } from "@playwright/test";

// E2E — вершина пирамиды: мало, медленно, только критичные пути. Поднимает оба
// сервера (FastAPI :8000 + Next :3000) или переиспользует уже запущенные локально.
export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 12_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // бэкенд: SQLite dev + AI-слой включён (как в документированном запуске)
      command: process.env.E2E_BACKEND_CMD ?? "python -m uvicorn main:app --port 8000",
      cwd: "..",
      url: "http://localhost:8000/health",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        AIOS_DATABASE_URL: "sqlite+aiosqlite:///./e2e.db",
        AIOS_AI_ENABLED: "true",
        PYTHONPATH: ".",
      },
    },
    {
      command: "npm run dev",
      url: "http://localhost:3000",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
