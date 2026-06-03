import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchMessages: vi.fn(),
  sendMessage: vi.fn(),
  aiDraftReply: vi.fn(),
}));

import { DealMessages } from "@/components/deal-messages";
import * as api from "@/lib/api";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

beforeEach(() => vi.clearAllMocks());

describe("DealMessages (омниканальный инбокс)", () => {
  it("показывает пустое состояние, когда переписки нет", async () => {
    mock(api.fetchMessages).mockResolvedValue([]);
    render(<DealMessages dealId="1" />);
    expect(await screen.findByText("Переписки пока нет")).toBeInTheDocument();
  });

  it("рендерит загруженные сообщения по каналам", async () => {
    mock(api.fetchMessages).mockResolvedValue([
      { id: 1, channel: "whatsapp", direction: "in", author: "Клиент", text: "Когда отгрузка?", created_at: "2026-06-02T14:00" },
    ]);
    render(<DealMessages dealId="2" />);
    expect(await screen.findByText("Когда отгрузка?")).toBeInTheDocument();
    expect(screen.getByText("Клиент")).toBeInTheDocument();
    expect(screen.getAllByText(/WhatsApp/).length).toBeGreaterThan(0);
  });

  it("отправляет сообщение по Enter", async () => {
    mock(api.fetchMessages).mockResolvedValue([]);
    mock(api.sendMessage).mockResolvedValue(true);
    render(<DealMessages dealId="3" />);
    await screen.findByText("Переписки пока нет");

    const input = screen.getByPlaceholderText("Написать сообщение...");
    fireEvent.change(input, { target: { value: "Здравствуйте" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(api.sendMessage).toHaveBeenCalledWith("3", "whatsapp", "Здравствуйте"));
  });

  it("AI-черновик подставляется в поле ввода", async () => {
    mock(api.fetchMessages).mockResolvedValue([]);
    mock(api.aiDraftReply).mockResolvedValue("Черновик ответа клиенту");
    render(<DealMessages dealId="4" />);
    await screen.findByText("Переписки пока нет");

    fireEvent.click(screen.getByText(/AI-черновик ответа/));
    await waitFor(() => expect(api.aiDraftReply).toHaveBeenCalledWith("4"));
    const input = screen.getByPlaceholderText("Написать сообщение...") as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe("Черновик ответа клиенту"));
  });
});
