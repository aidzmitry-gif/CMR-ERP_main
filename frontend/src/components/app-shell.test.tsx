import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/sidebar", () => ({ Sidebar: () => <div data-testid="sidebar" /> }));
vi.mock("@/components/topbar", () => ({
  Topbar: ({ crumbs }: { crumbs: string[] }) => <div data-testid="topbar">{crumbs.join("/")}</div>,
}));
// серверные зависимости AppShell: dev-сессия (логин/роль), редирект-гейт и матрица доступа
vi.mock("next/navigation", () => ({
  redirect: vi.fn(),
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));
vi.mock("@/lib/role-server", () => ({
  currentUserName: async () => "Харькович Д.С.",
  currentRole: async () => "director",
}));
vi.mock("@/lib/access", () => ({ fetchAccess: async () => null }));
// backendAuthHeaders зовёт cookies() (next/headers) — в vitest нет request store → мокаем шлюз
vi.mock("@/lib/auth-headers-server", () => ({ backendAuthHeaders: async () => ({}) }));

import { AppShell } from "@/components/app-shell";

describe("AppShell", () => {
  it("рендерит сайдбар, топбар с крошками и контент (вошедший пользователь)", async () => {
    // AppShell — async server component: вызываем как функцию и рендерим результат
    const ui = await AppShell({ crumbs: ["CRM", "Лиды"], children: <div>содержимое страницы</div> });
    render(ui);
    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("topbar")).toHaveTextContent("CRM/Лиды");
    expect(screen.getByText("содержимое страницы")).toBeInTheDocument();
  });
});
