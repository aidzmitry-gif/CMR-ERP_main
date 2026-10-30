import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorktimeView } from "./worktime-view";

const employee = { id: 1, full_name: "Тестовый сотрудник", department: "Отдел", position: "Специалист", status: "active" };
const session = { id: 9, employee_id: 1, work_date: "2026-10-30", started_at: "2026-10-30T06:00:00Z", ended_at: null, elapsed_seconds: 3600, present: false, last_seen_at: "2026-10-30T06:00:00Z" };
const policy = { id: 1, daily_minutes: 450, weekmask: 31, start_minute: null, manager_id: 2, effective_from: "2026-10-01", reference: "Тестовый договор" };
const context = { server_now: "2026-10-30T07:00:00Z", today: "2026-10-30", employee, session: null as typeof session | null, policy: policy as typeof policy | null, time_rule: "between_buttons", presence_affects_hours: false };
const day = { id: 4, employee_id: 1, date: "2026-10-30", worked_seconds: 32400, norm_minutes: 450, credited_minutes: 450, extra_minutes: 90, code: null, approval_status: "pending", can_decide: true };
const reply = (data: unknown, status = 200) => Promise.resolve({ ok: status >= 200 && status < 300, status, json: async () => data } as Response);
let current: typeof context;
let admin = false;
let handler: (url: string, init?: RequestInit) => Promise<Response>;
const fetcher = vi.fn((url: string, init?: RequestInit) => handler(url, init));

beforeEach(() => {
  current = structuredClone(context); admin = false; sessionStorage.clear(); fetcher.mockClear();
  handler = (url) => url.endsWith("/me/worktime") ? reply(current)
    : url.includes("/timesheet?") ? reply({ period: decodeURIComponent(url.split("period=")[1]), employees: [employee], items: [day], can_configure: admin, payroll_posted: false })
    : url.endsWith("/presence") ? reply(session) : reply({ detail: "Unexpected request" }, 500);
  vi.stubGlobal("fetch", fetcher);
});
afterEach(() => vi.unstubAllGlobals());

describe("Real worktime flow", () => {
  it("opens the month requested by an overtime notice", async () => {
    render(<WorktimeView initialTab="sheet" initialPeriod="2026-09" />);
    await screen.findByRole("button", { name: "Рассмотреть" });
    expect(screen.getByLabelText("Месяц")).toHaveValue("2026-09");
    expect(fetcher.mock.calls.some(([url]) => url.endsWith("period=2026-09"))).toBe(true);
  });
  it("does not invent a shift or contractual norm", async () => {
    current.policy = null; render(<WorktimeView />);
    expect(await screen.findByText("День ещё не начат")).toBeInTheDocument();
    expect(screen.getByLabelText("Время между кнопками")).toHaveTextContent("00:00:00");
    expect(screen.getByRole("button", { name: "Начать день" })).toBeDisabled();
    expect(screen.getByText(/Норма по договору: не настроена/)).toBeInTheDocument();
  });

  it("starts and ends only after server confirmation", async () => {
    const base = handler;
    handler = (url, init) => {
      if (url.endsWith("/start")) { current.session = session; return reply(session); }
      if (url.endsWith("/end")) { current.session = { ...session, ended_at: "2026-10-30T15:00:00Z", elapsed_seconds: 32400 }; return reply(current.session); }
      return base(url, init);
    };
    render(<WorktimeView />); fireEvent.click(await screen.findByRole("button", { name: "Начать день" }));
    fireEvent.click(await screen.findByRole("button", { name: "Завершить день" }));
    expect(await screen.findByText("День завершён")).toBeInTheDocument();
    const body = JSON.parse(fetcher.mock.calls.find(([url]) => url.endsWith("/end"))![1]!.body as string);
    expect(body).toMatchObject({ employee_id: 1, session_id: 9 });
    expect(body.request_key).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("keeps the same command identity across uncertain outcome and remount", async () => {
    const base = handler; let attempts = 0;
    handler = (url, init) => {
      if (url.endsWith("/start")) { attempts++; if (attempts === 1) return Promise.reject(new Error("Связь прервана")); current.session = session; return reply(session); }
      return base(url, init);
    };
    const first = render(<WorktimeView />); fireEvent.click(await screen.findByRole("button", { name: "Начать день" }));
    await screen.findByRole("button", { name: "Повторить начало дня" }); first.unmount();
    render(<WorktimeView />); fireEvent.click(await screen.findByRole("button", { name: "Повторить начало дня" }));
    await screen.findByRole("button", { name: "Завершить день" });
    const requests = fetcher.mock.calls.filter(([url]) => url.endsWith("/start"));
    expect(requests).toHaveLength(2); expect(requests[0][1]!.body).toEqual(requests[1][1]!.body);
  });

  it("does not present an authorization error as an empty day", async () => {
    handler = () => reply({ detail: "Доступ отозван" }, 403); render(<WorktimeView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Доступ отозван");
    expect(screen.queryByLabelText("Время между кнопками")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Начать день" })).not.toBeInTheDocument();
  });

  it("shows absent presence separately from a running shift", async () => {
    const base = handler;
    handler = (url, init) => url.endsWith("/board") ? reply({ server_now: current.server_now, items: [{ employee, session }], presence_affects_hours: false }) : base(url, init);
    render(<WorktimeView />); fireEvent.click(screen.getByRole("button", { name: "Кто онлайн" }));
    expect(await screen.findByText("Не подтверждено")).toBeInTheDocument();
    expect(screen.getByText("Начат")).toBeInTheDocument(); expect(screen.getByText("01:00:00")).toBeInTheDocument();
  });

  it("preserves the decision reason when the server refuses approval", async () => {
    const base = handler;
    handler = (url, init) => url.endsWith("/decision") ? reply({ detail: "Руководитель изменён" }, 403) : base(url, init);
    render(<WorktimeView />); fireEvent.click(screen.getByRole("button", { name: "Табель" }));
    fireEvent.click(await screen.findByRole("button", { name: "Рассмотреть" }));
    fireEvent.change(screen.getByLabelText("Основание решения"), { target: { value: "Проверено руководителем" } });
    fireEvent.click(screen.getByRole("button", { name: "Согласовать" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Руководитель изменён");
    expect(screen.getByLabelText("Основание решения")).toHaveValue("Проверено руководителем");
    expect(screen.getByText(/Ожидает согласования/)).toBeInTheDocument();
  });

  it("waits for a fresh timesheet after a confirmed approval", async () => {
    const base = handler; let saved = false;
    handler = (url, init) => {
      if (url.endsWith("/decision")) { saved = true; return reply({ id: 4, status: "approved" }); }
      if (saved && url.includes("/timesheet?")) return reply({ period: url.split("period=")[1], employees: [employee], items: [{ ...day, approval_status: "approved", can_decide: false, credited_minutes: 540 }] });
      return base(url, init);
    };
    render(<WorktimeView />); fireEvent.click(screen.getByRole("button", { name: "Табель" }));
    fireEvent.click(await screen.findByRole("button", { name: "Рассмотреть" }));
    fireEvent.change(screen.getByLabelText("Основание решения"), { target: { value: "Проверено" } });
    fireEvent.click(screen.getByRole("button", { name: "Согласовать" }));
    expect(await screen.findByText(/Согласована/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("ignores a late response for the previous timesheet month", async () => {
    const base = handler; let finish: ((response: Response) => void) | undefined;
    handler = (url, init) => url.includes("period=2025-01") ? new Promise(resolve => { finish = resolve; }) : base(url, init);
    render(<WorktimeView />); fireEvent.click(screen.getByRole("button", { name: "Табель" })); await screen.findByRole("button", { name: "Рассмотреть" });
    fireEvent.change(screen.getByLabelText("Месяц"), { target: { value: "2025-01" } });
    await waitFor(() => expect(finish).toBeDefined());
    fireEvent.change(screen.getByLabelText("Месяц"), { target: { value: "2025-02" } });
    await screen.findByRole("button", { name: "Рассмотреть" });
    await act(async () => finish!(await reply({ period: "2025-01", employees: [], items: [] })));
    expect(screen.getByRole("button", { name: "Рассмотреть" })).toBeInTheDocument();
  });

  it("saves an explicitly entered contract norm and chosen manager", async () => {
    admin = true; const base = handler;
    handler = (url, init) => url.endsWith("/settings") ? reply({ employees: [employee], managers: [{ id: 2, full_name: "Тестовый руководитель", employee_id: 2 }] })
      : url.endsWith("/policies") ? reply({ id: 8 }) : base(url, init);
    render(<WorktimeView />); fireEvent.click(await screen.findByRole("button", { name: "Настройки" }));
    const selectors = await screen.findAllByLabelText("Сотрудник");
    fireEvent.change(selectors[0], { target: { value: "1" } });
    const norm = screen.getByLabelText("Норма рабочего дня, минут"); expect(norm).toHaveValue(null);
    fireEvent.change(norm, { target: { value: "450" } }); fireEvent.click(screen.getByLabelText("Пн"));
    fireEvent.change(screen.getByLabelText("Руководитель"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Основание по договору"), { target: { value: "Тестовый договор" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить норму" }));
    expect(await screen.findByText(/Норма и руководитель сохранены/)).toBeInTheDocument();
    expect(JSON.parse(fetcher.mock.calls.find(([url]) => url.endsWith("/policies"))![1]!.body as string)).toMatchObject({ daily_minutes: 450, weekmask: 1, manager_id: 2, employee_id: 1 });
  });
});
