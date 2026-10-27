import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/api")>(),
  fetchAllCrmTasks: vi.fn(),
}));

import { TasksWorkspace } from "./tasks-workspace";
import * as api from "@/lib/api";

function task(id: number, dealId: number | null = null): api.DealTaskView {
  return { id, deal_id: dealId, title: `Задача ${id}`, kind: "other",
    assignee_id: null, due_at: null, status: "open", result: null, overdue: false };
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.fetchAllCrmTasks).mockResolvedValue([]);
});

describe("/crm/tasks workspace", () => {
  it("shows loading, then an unbound task without an invented deal link", async () => {
    let finish!: (rows: api.DealTaskView[]) => void;
    vi.mocked(api.fetchAllCrmTasks).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    render(<TasksWorkspace />);
    expect(screen.getByRole("status")).toHaveTextContent("Загрузка задач");
    finish([task(1)]);
    expect(await screen.findByText("Задача 1")).toBeInTheDocument();
    expect(screen.getByText("Без привязки к сделке")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(api.fetchAllCrmTasks).toHaveBeenCalledWith(0, 50);
  });

  it("paginates without dropping unbound tasks or guessing a total count", async () => {
    vi.mocked(api.fetchAllCrmTasks)
      .mockResolvedValueOnce(Array.from({ length: 50 }, (_, index) => task(index + 1)))
      .mockResolvedValueOnce([task(51)]);
    render(<TasksWorkspace />);
    expect(await screen.findByText("Задача 50")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Далее" }));
    expect(await screen.findByText("Задача 51")).toBeInTheDocument();
    expect(screen.queryByText("Задача 1")).not.toBeInTheDocument();
    expect(screen.getByText("Страница 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Далее" })).toBeDisabled();
    expect(api.fetchAllCrmTasks).toHaveBeenNthCalledWith(2, 50, 50);
  });

  it("separates failed load from empty state and retries the same page", async () => {
    vi.mocked(api.fetchAllCrmTasks).mockRejectedValueOnce(new Error("synthetic network"))
      .mockResolvedValueOnce([]);
    render(<TasksWorkspace />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить задачи");
    expect(screen.queryByText("Задач пока нет.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText("Задач пока нет.")).toBeInTheDocument();
    await waitFor(() => expect(api.fetchAllCrmTasks).toHaveBeenCalledTimes(2));
    expect(api.fetchAllCrmTasks).toHaveBeenNthCalledWith(2, 0, 50);
  });
});
