import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/api")>(),
  fetchDealTasks: vi.fn(),
  createDealTask: vi.fn(),
  completeDealTask: vi.fn(),
}));

import { DealTasks, TaskSummary } from "@/components/deal-tasks";
import * as api from "@/lib/api";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

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
  it.each(["pending", "failure"])("does not report zero tasks while the list is %s", async (state) => {
    const response = deferred<api.DealTaskView[]>();
    vi.mocked(api.fetchDealTasks).mockReturnValueOnce(response.promise);
    render(<DealTasks dealId="1" />);
    if (state === "failure") {
      await act(async () => response.reject(new Error("synthetic list unavailable")));
      expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить задачи");
    }
    expect(screen.getByText("(— откр.)")).toBeInTheDocument();
    expect(screen.queryByText("(0 откр.)")).not.toBeInTheDocument();
    expect(screen.queryByText("Задач пока нет")).not.toBeInTheDocument();
  });

  it("removes the old deal's tasks and draft immediately when the selected deal changes", async () => {
    const view = render(<DealTasks dealId="1" />);
    await screen.findByText("Перезвонить");
    fireEvent.change(screen.getByPlaceholderText("Что сделать…"), { target: { value: "Черновик первой сделки" } });
    const second = deferred<api.DealTaskView[]>();
    vi.mocked(api.fetchDealTasks).mockReturnValueOnce(second.promise);
    view.rerender(<DealTasks dealId="2" />);
    expect(screen.queryByText("Перезвонить")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Что сделать…")).toHaveValue("");
    expect(screen.getByText("(— откр.)")).toBeInTheDocument();
    await act(async () => second.resolve([]));
    expect(screen.getByText("Задач пока нет")).toBeInTheDocument();
    expect(screen.getByText("(0 откр.)")).toBeInTheDocument();
  });

  it("does not clear the new deal's draft or refresh the old deal after a late create response", async () => {
    const saved = deferred<boolean>();
    vi.mocked(api.createDealTask).mockReturnValueOnce(saved.promise);
    vi.mocked(api.fetchDealTasks).mockResolvedValue([]);
    const view = render(<DealTasks dealId="1" />);
    await screen.findByText("Задач пока нет");
    fireEvent.change(screen.getByPlaceholderText("Что сделать…"), { target: { value: "Первая сделка" } });
    fireEvent.click(screen.getByRole("button", { name: "Задача" }));
    view.rerender(<DealTasks dealId="2" />);
    await screen.findByText("Задач пока нет");
    fireEvent.change(screen.getByPlaceholderText("Что сделать…"), { target: { value: "Вторая сделка" } });
    await act(async () => saved.resolve(true));
    expect(screen.getByPlaceholderText("Что сделать…")).toHaveValue("Вторая сделка");
    expect(screen.getByRole("button", { name: "Задача" })).toBeEnabled();
    expect(api.fetchDealTasks).toHaveBeenCalledTimes(2);
    expect(api.createDealTask).toHaveBeenCalledTimes(1);
    expect(api.createDealTask).toHaveBeenCalledWith("1", { title: "Первая сделка", due_at: null });
  });

  it("keeps a refreshed list when an older initial read finishes after successful creation", async () => {
    const initial = deferred<api.DealTaskView[]>();
    vi.mocked(api.fetchDealTasks).mockReturnValueOnce(initial.promise).mockResolvedValueOnce([{
      id: 8, deal_id: 1, title: "Сохранённая задача", kind: "other", assignee_id: null,
      due_at: null, status: "open", result: null, overdue: false,
    }]);
    render(<DealTasks dealId="1" />);
    fireEvent.change(screen.getByPlaceholderText("Что сделать…"), { target: { value: "Сохранённая задача" } });
    fireEvent.click(screen.getByRole("button", { name: "Задача" }));
    await waitFor(() => expect(api.fetchDealTasks).toHaveBeenCalledTimes(2));
    await act(async () => initial.resolve([]));
    expect(await screen.findByText("Сохранённая задача")).toBeInTheDocument();
    expect(screen.getByText("(1 откр.)")).toBeInTheDocument();
    expect(screen.queryByText("Задач пока нет")).not.toBeInTheDocument();
  });

  it("does not display a late completion failure on a different deal", async () => {
    const completed = deferred<boolean>();
    vi.mocked(api.completeDealTask).mockReturnValueOnce(completed.promise);
    const view = render(<DealTasks dealId="1" />);
    fireEvent.click(await screen.findByTitle("Выполнено"));
    vi.mocked(api.fetchDealTasks).mockResolvedValueOnce([]);
    view.rerender(<DealTasks dealId="2" />);
    await screen.findByText("Задач пока нет");
    await act(async () => completed.reject(new Error("synthetic old-deal completion failure")));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("Перезвонить")).not.toBeInTheDocument();
    expect(api.completeDealTask).toHaveBeenCalledTimes(1);
    expect(api.fetchDealTasks).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["open", "Открыта"], ["in_progress", "В работе"],
    ["awaiting_control", "Ждёт контроля"], ["postponed", "Отложена"],
    ["done", "Выполнена"], ["declined", "Отклонена"], ["canceled", "Отменена"],
  ])("shows status %s as %s", (status, label) => {
    render(<ul><TaskSummary task={{ id: 99, deal_id: null, title: "Статус", kind: "other",
      assignee_id: null, due_at: null, status, result: null, overdue: false }} /></ul>);
    expect(screen.getByText(new RegExp(label))).toBeInTheDocument();
  });

  it("renders raw BBCode description as escaped text and links only returned numeric deal IDs", () => {
    const raw = '[URL=https://outside.example]ссылка[/URL]\n<img src=x onerror=alert(1)>';
    const { container } = render(<ul><TaskSummary task={{
      id: 99, deal_id: null, title: "Импорт", kind: "other", assignee_id: null,
      due_at: null, status: "in_progress", result: null, overdue: false,
      imported: true, description: raw, description_in_bbcode: true,
      crm_links: [
        { ordinal: 0, deal_id: 7 }, { ordinal: 1, deal_id: 7 },
        { ordinal: 2, deal_id: null }, { ordinal: 3, deal_id: -1 },
      ], hidden_link_count: 2,
    }} onDone={vi.fn()} /></ul>);
    expect(container.querySelector("p.whitespace-pre-wrap")?.textContent).toBe(raw);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getAllByRole("link")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Сделка 7" })).toHaveAttribute("href", "/crm/deals/7");
    expect(container.innerHTML).not.toContain("outside.example/");
    expect(screen.getByText("Скрытых связей: 2")).toBeInTheDocument();
    expect(screen.getByText("Импорт · только чтение")).toBeInTheDocument();
    expect(screen.queryByTitle("Выполнено")).not.toBeInTheDocument();
  });

  it("counts all four active statuses and prevents completion of imported tasks", async () => {
    vi.mocked(api.fetchDealTasks).mockResolvedValue([
      ...["open", "in_progress", "awaiting_control", "postponed", "done", "declined"].map((status, index) => ({
        id: index + 1, deal_id: 1, title: `Task ${index}`, kind: "other", assignee_id: null,
        due_at: null, status, result: null, overdue: false, imported: true,
      })),
    ]);
    render(<DealTasks dealId="1" />);
    expect(await screen.findByText("(4 откр.)")).toBeInTheDocument();
    expect(screen.queryByTitle("Выполнено")).not.toBeInTheDocument();
    expect(api.completeDealTask).not.toHaveBeenCalled();
  });

  it("reports a failed refresh after successful create as a list error, avoiding a duplicate retry", async () => {
    vi.mocked(api.fetchDealTasks).mockResolvedValueOnce([])
      .mockRejectedValueOnce(new Error("synthetic refresh failure"));
    render(<DealTasks dealId="1" />);
    await screen.findByText("Задач пока нет");
    fireEvent.change(screen.getByPlaceholderText("Что сделать…"), { target: { value: "Новая задача" } });
    fireEvent.click(screen.getByRole("button", { name: "Задача" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить задачи");
    expect(screen.queryByText("Не удалось создать задачу")).not.toBeInTheDocument();
    expect(api.createDealTask).toHaveBeenCalledTimes(1);
    expect(screen.getByPlaceholderText("Что сделать…")).toHaveValue("");
  });
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
