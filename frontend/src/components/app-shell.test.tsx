import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/sidebar", () => ({ Sidebar: () => <div data-testid="sidebar" /> }));
vi.mock("@/components/topbar", () => ({
  Topbar: ({ crumbs }: { crumbs: string[] }) => <div data-testid="topbar">{crumbs.join("/")}</div>,
}));

import { AppShell } from "@/components/app-shell";

describe("AppShell", () => {
  it("рендерит сайдбар, топбар с крошками и контент", () => {
    render(
      <AppShell crumbs={["CRM", "Лиды"]}>
        <div>содержимое страницы</div>
      </AppShell>,
    );
    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("topbar")).toHaveTextContent("CRM/Лиды");
    expect(screen.getByText("содержимое страницы")).toBeInTheDocument();
  });
});
