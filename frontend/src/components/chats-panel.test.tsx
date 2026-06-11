import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("@/lib/api", () => ({ fetchChats: vi.fn() }));

import { ChatsPanel } from "@/components/chats-panel";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

beforeEach(() => vi.clearAllMocks());

describe("ChatsPanel (Чаты и дела)", () => {
  it("рендерит список диалогов из API", async () => {
    mock(api.fetchChats).mockResolvedValue([
      { deal_id: 5, number: "CRM-5", company: "ООО Чат", last_text: "Уточните сроки", channel: "whatsapp", direction: "in" },
    ]);
    render(<ChatsPanel />);
    expect(await screen.findByText("ООО Чат")).toBeInTheDocument();
    expect(screen.getByText(/Уточните сроки/)).toBeInTheDocument();
    expect(screen.getByText("CRM-5")).toBeInTheDocument();
  });

  it("показывает пустое состояние без диалогов", async () => {
    mock(api.fetchChats).mockResolvedValue([]);
    render(<ChatsPanel />);
    expect(await screen.findByText("Диалогов пока нет")).toBeInTheDocument();
  });

  it("рендерит аватарку контрагента (инициалы) в свёрнутой рейке", async () => {
    mock(api.fetchChats).mockResolvedValue([
      { deal_id: 7, number: "CRM-7", company: "ООО Чат", last_text: "Привет", channel: "tg", direction: "in" },
    ]);
    render(<ChatsPanel />);
    // Свёрнутая рейка всегда показывает аватарку — инициалы видны без раскрытия.
    expect(await screen.findByText("ОЧ")).toBeInTheDocument();
  });

  it("показывает красный бейдж непрочитанных, когда unread > 0", async () => {
    mock(api.fetchChats).mockResolvedValue([
      { deal_id: 8, number: "CRM-8", company: "Гамма", last_text: "?", channel: "wa", direction: "in", unread: 3 },
    ]);
    render(<ChatsPanel />);
    const badge = await screen.findByTitle("Непрочитанных: 3");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent("3");
  });

  it("не показывает бейдж, когда поле unread отсутствует", async () => {
    mock(api.fetchChats).mockResolvedValue([
      { deal_id: 9, number: "CRM-9", company: "ООО Дельта", last_text: "ok", channel: "wa", direction: "out" },
    ]);
    render(<ChatsPanel />);
    await screen.findByText("ОД");
    expect(screen.queryByTitle(/Непрочитанных/)).not.toBeInTheDocument();
  });
});
