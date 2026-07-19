import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    // Запас под CI-нагрузкой: тяжёлые RTL-файлы с десятками async-ожиданий (deals-workspace,
    // leads-workspace) при контеншене превышали дефолтные 5с → редкий флейк.
    testTimeout: 15000,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    css: false,
    coverage: {
      provider: "v8",
      reporter: ["text-summary", "text", "json-summary", "html", "lcov"],
      include: ["src/lib/**", "src/components/**", "src/app/**"],
      exclude: ["src/**/*.{test,spec}.{ts,tsx}", "src/test/**", "src/lib/mock-data.ts"],
    },
  },
});
