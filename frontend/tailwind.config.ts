import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  darkMode: "class", // тёмная тема D — класс .dark на <html> (тоггл в Topbar)
  theme: {
    extend: {
      colors: {
        // Семантические токены интерфейса — читают CSS-переменные из globals.css.
        // Светлая тема C = :root, тёмная D = .dark. rgb(... / <alpha>) → работает opacity.
        accent: {
          DEFAULT: "rgb(var(--accent) / <alpha-value>)",
          ink: "rgb(var(--accent-ink) / <alpha-value>)",
          soft: "rgb(var(--accent-soft) / <alpha-value>)",
        },
        // Деньги — приоритет №1 (маржа/прибыль на видном месте)
        money: {
          DEFAULT: "rgb(var(--money) / <alpha-value>)",
          soft: "rgb(var(--money-soft) / <alpha-value>)",
        },
        brand: {
          DEFAULT: "#2563EB",
          50: "#EFF5FF",
          100: "#EAF1FF",
          600: "#2563EB",
          700: "#1D4FD7",
        },
        canvas: "rgb(var(--canvas) / <alpha-value>)",
        surface: "rgb(var(--surface) / <alpha-value>)",
        sunken: "rgb(var(--sunken) / <alpha-value>)",
        ink: "rgb(var(--ink) / <alpha-value>)",
        muted: "rgb(var(--muted) / <alpha-value>)",
        faint: "rgb(var(--faint) / <alpha-value>)",
        line: "rgb(var(--line) / <alpha-value>)",
        "line-strong": "rgb(var(--line-strong) / <alpha-value>)",
        // цвета стадий воронки
        stage: {
          new: "#3B82F6",
          qual: "#8B5CF6",
          prop: "#F59E0B",
          appr: "#14B8A6",
          won: "#22C55E",
        },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Arial", "sans-serif"],
      },
      boxShadow: {
        // мягкая многослойная тень + верхняя подсветка — «дорогой» вид
        card: "0 1px 1px rgba(20,20,40,0.03), 0 2px 4px rgba(20,20,40,0.04), 0 6px 16px rgba(20,20,40,0.04), inset 0 1px 0 rgba(255,255,255,0.6)",
        pop: "0 1px 2px rgba(20,20,40,0.06), 0 12px 28px rgba(20,20,40,0.12)",
      },
      borderRadius: {
        lg: "10px",
        xl: "12px",
        "2xl": "14px",
      },
    },
  },
  plugins: [],
};

export default config;
