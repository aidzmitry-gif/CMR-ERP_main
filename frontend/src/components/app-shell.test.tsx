import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/sidebar", () => ({ Sidebar: () => <div data-testid="sidebar" /> }));
vi.mock("@/components/topbar", () => ({
  Topbar: ({ crumbs }: { crumbs: string[] }) => <div data-testid="topbar">{crumbs.join("/")}</div>,
}));
// серверные зависимости AppShell: cookie текущей роли и загрузка матрицы доступа
vi.mock("next/headers", () => ({ cookies: async () => ({ get: () => undefined }) }));
vi.mock("@/lib/access", () => ({
  ROLE_COOKIE: "aios_role",
  DEFAULT_ROLE: "director",
  fetchAccess: async () => null,
}));

import { AppShell } from "@/components/app-shell";

describe("AppShell", () => {
  it("рендерит сайдбар, топбар с крошками и контент", async () => {
    // AppShell — async server component: вызываем как функцию и рендерим результат
    const ui = await AppShell({ crumbs: ["CRM", "Лиды"], children: <div>содержимое страницы</div> });
    render(ui);
    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("topbar")).toHaveTextContent("CRM/Лиды");
    expect(screen.getByText("содержимое страницы")).toBeInTheDocument();
  });
});
