import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LeadActivity } from "./lead-activity";
import { type ActivityResult, type ActivityTask, readActivityMessages, readActivityTasks } from "@/lib/lead-activity";

vi.mock("@/lib/lead-activity", async (original) => ({
  ...await original<typeof import("@/lib/lead-activity")>(),
  readActivityTasks: vi.fn(), readActivityMessages: vi.fn(),
}));
const tasks = vi.mocked(readActivityTasks);
const messages = vi.mocked(readActivityMessages);
const task: ActivityTask = { id: 1, deal_id: 4, title: "Контрольный звонок", kind: "call", due_at: null, status: "open", overdue: false };
const base = { nextStepAt: null, nextStepNote: "" };
beforeEach(() => {
  vi.clearAllMocks();
  tasks.mockResolvedValue({ status: "ok", rows: [] });
  messages.mockResolvedValue({ status: "ok", rows: [] });
});

describe("full lead activity", () => {
  it.each([undefined, 0, -1, NaN])("shows saved next step without fake requests for deal %s", (dealId) => {
    render(<LeadActivity {...base} dealId={dealId} nextStepNote="Подготовить предложение" />);
    expect(screen.getByText("Подготовить предложение")).toBeInTheDocument();
    expect(screen.getByText("Срок не указан")).toBeInTheDocument();
    expect(screen.getByText(/Связанная сделка не указана/)).toBeInTheDocument();
    expect(tasks).not.toHaveBeenCalled(); expect(messages).not.toHaveBeenCalled();
  });
  it("does not present loading as zero tasks or messages", async () => {
    tasks.mockReturnValue(new Promise(() => {})); messages.mockReturnValue(new Promise(() => {}));
    render(<LeadActivity {...base} dealId={4} />);
    expect(screen.getAllByRole("status")).toHaveLength(2);
    expect(screen.queryByText(/задач пока нет/)).not.toBeInTheDocument();
    expect(screen.queryByText(/записей общения пока нет/)).not.toBeInTheDocument();
  });
  it("renders linked data and preserves a failed feed independently; retry recovers", async () => {
    tasks.mockResolvedValueOnce({ status: "error", reason: "access" })
      .mockResolvedValueOnce({ status: "ok", rows: [task] });
    messages.mockResolvedValue({ status: "ok", rows: [{ id: 2, channel: "email", direction: "out",
      author: "Менеджер", text: "История разговора", created_at: "2026-09-13T10:00:00" }] });
    render(<LeadActivity {...base} dealId={4} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Недостаточно прав");
    expect(await screen.findByText("История разговора")).toBeInTheDocument();
    expect(screen.queryByText(/задач пока нет/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(await screen.findByText("Контрольный звонок")).toBeInTheDocument();
    expect(messages).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("link", { name: /для работы с задачами/ })).toHaveAttribute("href", "/crm/deals/4");
    expect(screen.getByText(/не подтверждает доставку/)).toBeInTheDocument();
  });
  it("shows successful empty feeds and saved deadline", async () => {
    render(<LeadActivity {...base} dealId={4} nextStepAt="2026-09-14T07:00:00" />);
    expect(await screen.findByText("В связанной сделке задач пока нет.")).toBeInTheDocument();
    expect(await screen.findByText("В связанной сделке записей общения пока нет.")).toBeInTheDocument();
    expect(screen.getByText("Заметка не указана")).toBeInTheDocument();
    expect(screen.getByText("14.09.2026, 10:00:00 (Минск)")).toBeInTheDocument();
  });
  it("does not show a late result from the previous linked deal", async () => {
    let resolve!: (value: ActivityResult<ActivityTask>) => void;
    tasks.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
    const view = render(<LeadActivity {...base} dealId={4} />);
    const oldSignal = tasks.mock.calls[0][1];
    view.rerender(<LeadActivity {...base} dealId={5} />);
    await screen.findByText("В связанной сделке задач пока нет.");
    await act(async () => { resolve({ status: "ok", rows: [task] }); });
    expect(oldSignal?.aborted).toBe(true);
    expect(screen.queryByText("Контрольный звонок")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /для работы с задачами/ })).toHaveAttribute("href", "/crm/deals/5");
  });
  it("aborts both pending feeds on unmount", async () => {
    const view = render(<LeadActivity {...base} dealId={4} />);
    await waitFor(() => expect(messages).toHaveBeenCalledTimes(1));
    view.unmount();
    expect(tasks.mock.calls[0][1]?.aborted).toBe(true);
    expect(messages.mock.calls[0][1]?.aborted).toBe(true);
  });
});
