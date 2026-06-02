import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#2563EB",
          50: "#EFF5FF",
          100: "#EAF1FF",
          600: "#2563EB",
          700: "#1D4FD7",
        },
        canvas: "#F4F5F7",
        ink: "#1F2937",
        muted: "#6B7280",
        // цвета стадий воронки
        stage: {
          new: "#3B82F6",
          qual: "#8B5CF6",
          prop: "#F59E0B",
          appr: "#14B8A6",
          won: "#22C55E",
        },
      },
      boxShadow: {
        card: "0 1px 2px rgba(16,24,40,0.04), 0 1px 3px rgba(16,24,40,0.06)",
        pop: "0 8px 24px rgba(16,24,40,0.10)",
      },
      borderRadius: {
        xl: "12px",
        "2xl": "16px",
      },
    },
  },
  plugins: [],
};

export default config;
