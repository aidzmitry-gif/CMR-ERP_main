import { defineConfig, devices } from "@playwright/test";
import { resolve } from "node:path";

const isolatedBase = process.env.E2E_ISOLATED_BASE_URL;
const localPort = (name: string, fallback: number) => {
  const raw = process.env[name] ?? String(fallback);
  const port = Number(raw);
  if (!/^\d+$/.test(raw) || !Number.isSafeInteger(port) || port < 1024 || port > 65535) {
    throw new Error(`${name} must be an integer port between 1024 and 65535`);
  }
  return port;
};
const backendPort = localPort("E2E_BACKEND_PORT", 8000);
const frontendPort = localPort("E2E_FRONTEND_PORT", 4000);
if (backendPort === frontendPort) throw new Error("E2E backend and frontend ports must differ");
if (isolatedBase && !/^http:\/\/127\.0\.0\.1:\d+$/.test(isolatedBase)) {
  throw new Error("E2E_ISOLATED_BASE_URL must be an explicit IPv4 loopback URL");
}

// E2E — вершина пирамиды: мало, медленно, только критичные пути. Поднимает оба
// сервера (FastAPI :8000 + Next :4000) с отдельной синтетической базой.
export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 12_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    // Порт 4000: 3000/3001 заняты SEO-проектом на этой машине.
    baseURL: isolatedBase ?? `http://localhost:${frontendPort}`,
    trace: "retain-on-failure",
    launchOptions: process.env.E2E_CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.E2E_CHROMIUM_EXECUTABLE } : undefined,
  },
  projects: [
    // 1) разовый dev-логин → storageState (см. e2e/auth.setup.ts)
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    // 2) сами сценарии — стартуют уже вошедшими (переиспользуют сессию из setup)
    {
      name: "chromium",
      testIgnore: /auth\.setup\.ts/,
      use: { ...devices["Desktop Chrome"], storageState: "e2e/.auth/state.json" },
      dependencies: ["setup"],
    },
  ],
  webServer: isolatedBase ? undefined : [
    {
      // Синтетическая SQLite, без фоновых интеграций и внешних соединений.
      // CI (Linux) ставит зависимости в СИСТЕМНЫЙ python (venv нет) → на не-Windows зовём `python`,
      // иначе `.venv/bin/python` не найден и webServer падает exit 127. Windows-локаль — .venv для удобства.
      // Особый случай (свой интерпретатор) — через E2E_BACKEND_CMD.
      command: process.env.E2E_BACKEND_CMD ??
        `${process.platform === "win32" ? ".venv\\Scripts\\python.exe" : "python"} frontend/e2e/backend.py`,
      env: { E2E_SQLITE_PATH: resolve(process.cwd(), "..", "e2e.db"), E2E_BIND_PORT: String(backendPort) },
      cwd: "..",
      url: `http://localhost:${backendPort}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npm run dev -- -p ${frontendPort}`,
      env: { BACKEND_URL: `http://127.0.0.1:${backendPort}`, NEXT_PUBLIC_AUTH_MODE: "dev" },
      url: `http://localhost:${frontendPort}`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
