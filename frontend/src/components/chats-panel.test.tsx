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
});
