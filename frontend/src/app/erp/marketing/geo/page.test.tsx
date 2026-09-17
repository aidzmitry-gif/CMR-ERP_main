import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/app-shell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

import MarketingGeoPage from "@/app/erp/marketing/geo/page";

describe("MarketingGeoPage", () => {
  it("рендерит регионы, KPI-фабрики и очередь публикаций", () => {
    render(<MarketingGeoPage />);
    expect(screen.getByRole("heading", { name: "Гео-фабрика" })).toBeInTheDocument();
    expect(screen.getByText("49")).toBeInTheDocument();
    expect(screen.getByText("72%")).toBeInTheDocument();
    expect(screen.getByText("Минск")).toBeInTheDocument();
    expect(screen.getByText("Гомель")).toBeInTheDocument();
    expect(screen.getByText("Витебск")).toBeInTheDocument();
    expect(screen.getByText("Брест")).toBeInTheDocument();
    expect(screen.getByText("Проверить каннибализацию Минск/область")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /SEO-проекты/ })).toHaveAttribute("href", "/erp/marketing/seo");
  });
});
