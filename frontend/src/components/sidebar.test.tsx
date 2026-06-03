import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

import { Sidebar } from "@/components/sidebar";

describe("Sidebar", () => {
  it("рендерит навигацию по модулям, включая лиды и сделки", () => {
    render(<Sidebar />);
    expect(screen.getByText("CRM")).toBeInTheDocument();
    expect(screen.getByText("Лиды")).toBeInTheDocument();
    expect(screen.getByText("Сделки")).toBeInTheDocument();
    expect(screen.getByText("Закупки")).toBeInTheDocument();
    expect(screen.getByText("HR")).toBeInTheDocument();
  });
});
