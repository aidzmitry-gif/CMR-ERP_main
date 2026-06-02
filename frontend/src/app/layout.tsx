import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI-OS — CRM",
  description: "AI-First Business Operating System",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
