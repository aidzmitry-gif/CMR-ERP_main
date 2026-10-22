import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children, ...props }: React.ComponentProps<"a">) => (
    <a {...props}>{children}</a>
  ),
}));
vi.mock("@/lib/api", () => ({ fetchEvents: vi.fn() }));

import { Topbar } from "@/components/topbar";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
beforeEach(() => vi.clearAllMocks());

describe("Topbar", () => {
  it("AVATAR-IDENTITY-LINK shows the supplied user's initials and profile link", () => {
    render(<Topbar crumbs={["ERP"]} userName="Анна Волкова" />);
    const avatar = screen.getByRole("link", { name: "Анна Волкова — Моя карточка" });
    expect(avatar).toHaveTextContent("АВ");
    expect(avatar).toHaveAttribute("href", "/profile");
    expect(avatar).toHaveAttribute("title", "Анна Волкова — Моя карточка");
    expect(screen.queryByText("ИП")).not.toBeInTheDocument();
  });

  it("AVATAR-IDENTITY-CHANGE updates the identity when the user changes", () => {
    const { rerender } = render(<Topbar crumbs={["ERP"]} userName="Анна Волкова" />);
    rerender(<Topbar crumbs={["ERP"]} userName="Борис Синицын" />);
    expect(screen.getByRole("link", { name: "Борис Синицын — Моя карточка" })).toHaveTextContent("БС");
    expect(screen.queryByRole("link", { name: "Анна Волкова — Моя карточка" })).not.toBeInTheDocument();
  });

  it("AVATAR-ABSENT-BLANK does not invent a user when the name is missing or blank", () => {
    const { rerender, container } = render(<Topbar crumbs={["ERP"]} />);
    expect(container.querySelector('a[href="/profile"]')).toBeNull();
    for (const userName of ["", "   "]) {
      rerender(<Topbar crumbs={["ERP"]} userName={userName} />);
      expect(container.querySelector('a[href="/profile"]')).toBeNull();
      expect(screen.queryByText("ИП")).not.toBeInTheDocument();
    }
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
