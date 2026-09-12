import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/api")>(),
  fetchDealTasks: vi.fn(),
  createDealTask: vi.fn(),
  completeDealTask: vi.fn(),
}));

import { DealTasks } from "@/components/deal-tasks";
import * as api from "@/lib/api";

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.fetchDealTasks).mockResolvedValue([
    {
      id: 1, deal_id: 1, title: "Перезвонить", kind: "call", assignee_id: null,
      due_at: "2020-01-01T10:00:00", status: "open", result: null, overdue: true,
    },
    {
      id: 2, deal_id: 1, title: "Готово", kind: "other", assignee_id: null,
      due_at: null, status: "done", result: "ok", overdue: false,
    },
  ]);
  vi.mocked(api.createDealTask).mockResolvedValue(true);
  vi.mocked(api.completeDealTask).mockResolvedValue(true);
});

describe("DealTasks", () => {
  it.each(["2026-09-15T07:00:00", "2026-09-15T07:00:00Z", "2026-09-15T10:00:00+03:00"])(
    "показывает UTC-срок %s в местном времени менеджера",
    async (due_at) => {
      vi.mocked(api.fetchDealTasks).mockResolvedValue([{
        id: 9, deal_id: 1, title: "Проверить срок", kind: "call", assignee_id: null,
        due_at, status: "open", result: null, overdue: false,
      }]);
      render(<DealTasks dealId="1" />);
      await screen.findByText("Проверить срок");
      const localHour = new Date("2026-09-15T07:00:00Z").getHours().toString().padStart(2, "0");
      expect(screen.getByText(new RegExp(`Звонок · .*${localHour}:00`))).toBeInTheDocument();
    },
  );

  it("рендерит задачи, считает открытые и подсвечивает просрочку", async () => {
    render(<DealTasks dealId="1" />);
    await waitFor(() => expect(screen.getByText("Перезвонить")).toBeInTheDocument());
    expect(screen.getByText("Готово")).toBeInTheDocument();
    expect(screen.getByText("(1 откр.)")).toBeInTheDocument(); // только одна открытая
    expect(screen.getByText(/просрочено/)).toBeInTheDocument();
  });

  it.each(["false", "rejection"])("сохраняет задачу и срок при %s, разрешает успешный повтор", async (failure) => {
    vi.mocked(api.fetchDealTasks).mockResolvedValue([]);
    const create = vi.mocked(api.createDealTask);
    if (failure === "false") create.mockResolvedValueOnce(false);
    else create.mockRejectedValueOnce(new Error("network unavailable"));
    create.mockResolvedValueOnce(true);

    render(<DealTasks dealId="1" />);
    await screen.findByText("Задач пока нет");
    const title = screen.getByPlaceholderText("Что сделать…");
    const due = screen.getByTitle("Срок (необязательно)");
    const add = screen.getByRole("button", { name: "Задача" });
    fireEvent.change(title, { target: { value: "Перезвонить Анне" } });
    fireEvent.change(due, { target: { value: "2026-09-15T10:00" } });
    fireEvent.click(add);

    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось создать задачу");
    expect(title).toHaveValue("Перезвонить Анне");
    expect(due).toHaveValue("2026-09-15T10:00");
    expect(add).toBeEnabled();
    expect(api.fetchDealTasks).toHaveBeenCalledTimes(1);

    vi.mocked(api.fetchDealTasks).mockResolvedValueOnce([{
      id: 3, deal_id: 1, title: "Перезвонить Анне", kind: "other", assignee_id: null,
      due_at: "2026-09-15T10:00", status: "open", result: null, overdue: false,
    }]);
    fireEvent.click(add);
    expect(await screen.findByText("Перезвонить Анне")).toBeInTheDocument();
    expect(create).toHaveBeenNthCalledWith(2, "1", {
      title: "Перезвонить Анне", due_at: new Date("2026-09-15T10:00").toISOString().slice(0, 19),
    });
    expect(title).toHaveValue("");
    expect(due).toHaveValue("");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each(["false", "rejection"])("показывает ошибку завершения при %s и разрешает повтор", async (failure) => {
    const task = {
      id: 4, deal_id: 1, title: "Проверить ответ", kind: "other", assignee_id: null,
      due_at: null, status: "open", result: null, overdue: false,
    };
    vi.mocked(api.fetchDealTasks).mockResolvedValue([task]);
    const complete = vi.mocked(api.completeDealTask);
    if (failure === "false") complete.mockResolvedValueOnce(false);
    else complete.mockRejectedValueOnce(new Error("network unavailable"));
    complete.mockResolvedValueOnce(true);

    render(<DealTasks dealId="1" />);
    const done = await screen.findByTitle("Выполнено");
    fireEvent.click(done);
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось завершить задачу");
    expect(done).toBeEnabled();
    expect(screen.getByText("(1 откр.)")).toBeInTheDocument();
    expect(api.fetchDealTasks).toHaveBeenCalledTimes(1);

    vi.mocked(api.fetchDealTasks).mockResolvedValueOnce([{ ...task, status: "done" }]);
    fireEvent.click(done);
    expect(await screen.findByText("✓ готово")).toBeInTheDocument();
    expect(complete).toHaveBeenNthCalledWith(2, 4);
    expect(screen.getByText("(0 откр.)")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
