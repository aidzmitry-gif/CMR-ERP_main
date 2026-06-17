import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Script from "next/script";
import { THEME_INIT_SCRIPT } from "@/components/theme-toggle";
import "./globals.css";

// Интерфейсный шрифт дизайн-системы (Stripe/Notion). Переменная используется в tailwind.config (fontFamily.sans).
const inter = Inter({ subsets: ["latin", "cyrillic"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: "AI-OS — CRM",
  description: "AI-First Business Operating System",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" className={inter.variable} suppressHydrationWarning>
      <head>
        {/* Ставит .dark до рендера — без вспышки светлого при загрузке тёмной темы.
            Контент статичен (константа), не из пользовательского ввода — XSS-риска нет. */}
        <Script id="theme-init" strategy="beforeInteractive">
          {THEME_INIT_SCRIPT}
        </Script>
      </head>
      <body>{children}</body>
    </html>
  );
}
