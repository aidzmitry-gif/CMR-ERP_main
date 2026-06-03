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
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    css: false,
    coverage: {
      provider: "v8",
      reporter: ["text-summary", "text", "json-summary", "html", "lcov"],
      include: ["src/lib/**", "src/components/**"],
      exclude: ["src/**/*.{test,spec}.{ts,tsx}", "src/test/**", "src/lib/mock-data.ts"],
    },
  },
});
