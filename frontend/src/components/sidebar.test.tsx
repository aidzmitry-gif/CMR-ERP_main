import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// В этом тест-окружении нет window.localStorage — сайдбар читает его в try/catch,
// потому не падает, но остаётся свёрнутым (default collapsed). Стабаем хранилище так,
// чтобы эффект гидрации развернул rail (collapsed="0") и подписи попали в DOM.
beforeEach(() => {
  const store: Record<string, string> = { "aios-sidebar-collapsed": "0" };
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => {
      store[k] = v;
    },
    removeItem: (k: string) => {
      delete store[k];
    },
    clear: () => {
      for (const k of Object.keys(store)) delete store[k];
    },
  });
});

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/crm/deals",
  useRouter: () => ({ refresh: vi.fn() }),
}));

import { Sidebar } from "@/components/sidebar";

describe("Sidebar", () => {
  it("рендерит навигацию по модулям, включая лиды и сделки", async () => {
    // Сайдбар по умолчанию — свёрнутый rail (collapsed); подписи модулей есть в DOM
    // только при развороте (showFull). Разворачиваем через localStorage-настройку,
    // которую читает эффект гидрации (COLLAPSED_KEY="aios-sidebar-collapsed").
    localStorage.setItem("aios-sidebar-collapsed", "0");
    render(<Sidebar />);
    expect(await screen.findByText("CRM")).toBeInTheDocument();
    expect(screen.getByText("Лиды")).toBeInTheDocument();
    expect(screen.getByText("Сделки")).toBeInTheDocument();
    expect(screen.getByText("Закупки")).toBeInTheDocument();
    expect(screen.getByText("HR")).toBeInTheDocument();
  });
});
