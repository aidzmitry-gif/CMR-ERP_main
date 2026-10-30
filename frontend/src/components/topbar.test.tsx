import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string; title?: string }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));
vi.mock("@/lib/api", () => ({ fetchEvents: vi.fn() }));

import { Topbar } from "@/components/topbar";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
beforeEach(() => vi.clearAllMocks());

describe("Topbar", () => {
  it("shows the signed-in user's initials and opens their profile", () => {
    render(<Topbar crumbs={["ERP"]} userName="Дмитрий Сергеевич" />);
    expect(screen.getByRole("link", { name: "ДС" })).toHaveAttribute("href", "/profile");
    expect(screen.getByTitle("Дмитрий Сергеевич — Моя карточка")).toHaveTextContent("ДС");
    expect(screen.queryByText("ИП")).not.toBeInTheDocument();
  });
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

  it("закрывает поповер по клику на подложку", () => {
    mock(api.fetchEvents).mockResolvedValue([]);
    const { container } = render(<Topbar crumbs={["CRM"]} />);
    fireEvent.click(screen.getByTitle("Уведомления"));
    expect(screen.getByText("Уведомления")).toBeInTheDocument();
    fireEvent.click(container.querySelector(".fixed.inset-0") as HTMLElement);
    expect(screen.queryByText("Уведомления")).toBeNull();
  });
});
