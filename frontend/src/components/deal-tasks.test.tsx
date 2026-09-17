import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchDealTasks: vi.fn(),
  createDealTask: vi.fn().mockResolvedValue(true),
  completeDealTask: vi.fn().mockResolvedValue(true),
}));

import { DealTasks } from "@/components/deal-tasks";
import * as api from "@/lib/api";

beforeEach(() => vi.clearAllMocks());

describe("DealTasks", () => {
  it("показывает пустое состояние и создаёт задачу с необязательным сроком", async () => {
    (api.fetchDealTasks as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]).mockResolvedValueOnce([]);
    render(<DealTasks dealId="deal-1" />);
    expect(await screen.findByText("Задач пока нет")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("Что сделать…"), { target: { value: "Отправить КП" } });
    fireEvent.change(screen.getByTitle("Срок (необязательно)"), { target: { value: "2026-09-20T10:00" } });
    fireEvent.click(screen.getByRole("button", { name: /Задача/ }));
    await waitFor(() =>
      expect(api.createDealTask).toHaveBeenCalledWith("deal-1", {
        title: "Отправить КП",
        due_at: "2026-09-20T10:00",
      }),
    );
  });

  it("рендерит просроченную/выполненную задачу и отмечает открытую выполненной", async () => {
    (api.fetchDealTasks as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { id: 1, title: "Позвонить", kind: "call", due_at: "2020-01-01T10:00:00", status: "open", overdue: true },
      { id: 2, title: "Договор", kind: "doc", due_at: null, status: "done", overdue: false },
    ]).mockResolvedValueOnce([]);
    render(<DealTasks dealId="deal-2" />);
    expect(await screen.findByText(/просмотрено|просрочено/)).toBeInTheDocument();
    expect(screen.getByText("✓ готово")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Выполнено"));
    await waitFor(() => expect(api.completeDealTask).toHaveBeenCalledWith(1));
  });
});
