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

beforeEach(() => vi.resetAllMocks());

describe("DealMessages (история общения)", () => {
  it("показывает пустое состояние, когда переписки нет", async () => {
    mock(api.fetchMessages).mockResolvedValue([]);
    render(<DealMessages dealId="1" />);
    expect(await screen.findByText("Переписки пока нет")).toBeInTheDocument();
    expect(screen.getByText(/Клиенту сообщение не отправляется/)).toBeInTheDocument();
  });

  it.each(["false", "rejection"])("при %s сохраняет текст и позволяет повторить запись", async (failure) => {
    vi.mocked(api.fetchMessages).mockResolvedValue([]);
    if (failure === "false") vi.mocked(api.sendMessage).mockResolvedValueOnce(false);
    else vi.mocked(api.sendMessage).mockRejectedValueOnce(new Error("offline"));
    vi.mocked(api.sendMessage).mockResolvedValueOnce(true);
    render(<DealMessages dealId="1" />);
    const input = screen.getByPlaceholderText("Написать сообщение...");
    fireEvent.change(input, { target: { value: "Согласовали доставку" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить запись в историю" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось сохранить запись");
    expect(input).toHaveValue("Согласовали доставку");
    const save = screen.getByRole("button", { name: "Сохранить запись в историю" });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() => expect(input).toHaveValue(""));
    expect(api.sendMessage).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("повторный Enter во время сохранения не создаёт вторую запись", async () => {
    vi.mocked(api.fetchMessages).mockResolvedValue([]);
    let finish!: (value: boolean) => void;
    vi.mocked(api.sendMessage).mockReturnValue(new Promise(resolve => { finish = resolve; }));
    render(<DealMessages dealId="1" />);
    const input = screen.getByPlaceholderText("Написать сообщение...");
    fireEvent.change(input, { target: { value: "Подтверждение" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(api.sendMessage).toHaveBeenCalledTimes(1);
    finish(true);
    await waitFor(() => expect(input).toHaveValue(""));
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

  it("сохраняет запись по Enter", async () => {
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

  it("показывает заглушку, если AI вернул null", async () => {
    mock(api.fetchMessages).mockResolvedValue([]);
    mock(api.aiDraftReply).mockResolvedValue(null);
    render(<DealMessages dealId="5" />);
    await screen.findByText("Переписки пока нет");
    fireEvent.click(screen.getByText(/AI-черновик ответа/));
    expect(await screen.findByText(/AI-слой выключен/)).toBeInTheDocument();
  });

  it("сохраняет выбранный канал записи", async () => {
    mock(api.fetchMessages).mockResolvedValue([]);
    mock(api.sendMessage).mockResolvedValue(true);
    render(<DealMessages dealId="6" />);
    await screen.findByText("Переписки пока нет");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "telegram" } });
    const input = screen.getByPlaceholderText("Написать сообщение...");
    fireEvent.change(input, { target: { value: "Привет" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(api.sendMessage).toHaveBeenCalledWith("6", "telegram", "Привет"));
  });
});
