import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("@/lib/api", () => ({ fetchEvents: vi.fn() }));

import { Topbar } from "@/components/topbar";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
beforeEach(() => vi.clearAllMocks());

describe("Topbar", () => {
  it("показывает хлебные крошки", () => {
    render(<Topbar crumbs={["CRM", "Сделки"]} />);
    expect(screen.getByText("CRM")).toBeInTheDocument();
    expect(screen.getByText("Сделки")).toBeInTheDocument();
  });

  it("открывает уведомления и грузит события", async () => {
    mock(api.fetchEvents).mockResolvedValue([
      { id: 1, event_type: "sales.deal.created", created_at: "2026-06-02T14:00", processed: false },
    ]);
    render(<Topbar crumbs={["CRM"]} />);
    fireEvent.click(screen.getByTitle("Уведомления"));
    expect(await screen.findByText("Создана сделка")).toBeInTheDocument();
  });

  it("открывает справку", () => {
    render(<Topbar crumbs={["CRM"]} />);
    fireEvent.click(screen.getByTitle("Помощь"));
    expect(screen.getByText(/AI-First Business OS/)).toBeInTheDocument();
  });
});
