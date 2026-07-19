import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HrPayrollView } from "@/components/erp/hr-payroll-view";

// ──────────────────────────── Фикстуры ────────────────────────────

const employees = [
  { id: 1, full_name: "Иванов Иван", position: "Слесарь" },
  { id: 2, full_name: "Петрова Анна", position: "Бухгалтер" },
];

const summaries = [
  { period: "2026-06", total_byn: "3500.00", count: 2, pending_count: 1 },
  { period: "2026-05", total_byn: "1200.50", count: 1, pending_count: 0 },
];

// Начисления по умолчанию (все) и по конкретному периоду.
const allEntries = [
  { id: 10, employee_id: 1, period: "2026-06", amount_byn: "1500.00", status: "pending" },
  { id: 11, employee_id: 2, period: "2026-06", amount_byn: "2000.00", status: "paid" },
];
const junePeriodEntries = [
  { id: 10, employee_id: 1, period: "2026-06", amount_byn: "1500.00", status: "pending" },
];

// Нормализованный матчер денег: убираем пробелы-разделители (в т. ч. NBSP), decimal
// separator у ru-BY — запятая, но допускаем и точку на случай урезанного ICU.
function moneyText(target: string) {
  return (content: string) => {
    const n = content.replace(/\s/g, "");
    return n.includes(`${target},`) || n.includes(`${target}.`);
  };
}

function jsonResponse(data: unknown, ok = true, status = 200) {
  return Promise.resolve({
    ok,
    status,
    json: async () => data,
  } as Response);
}

// Роутер-мок глобального fetch: разводит по URL (компонент ходит в /api/hr/* напрямую).
type FetchOverrides = {
  accrueResponse?: () => Promise<Response>;
};

function installFetch(overrides: FetchOverrides = {}) {
  const mock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.startsWith("/api/hr/payroll/summary")) return jsonResponse(summaries);
    if (url.startsWith("/api/hr/payroll/accrue")) {
      return overrides.accrueResponse
        ? overrides.accrueResponse()
        : jsonResponse({ ok: true });
    }
    if (url.startsWith("/api/hr/payroll/pay")) return jsonResponse({ ok: true });
    if (url.startsWith("/api/hr/payroll")) {
      // ?period=... → детализация периода, иначе — общий список (с учётом ?status=)
      if (url.includes("period=")) return jsonResponse(junePeriodEntries);
      return jsonResponse(allEntries);
    }
    if (url.startsWith("/api/hr/employees")) return jsonResponse(employees);
    return jsonResponse({});
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function fetchCalls(mock: ReturnType<typeof vi.fn>): string[] {
  return mock.mock.calls.map((c) => String(c[0]));
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = installFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("HrPayrollView", () => {
  it("рендерит заголовок и ведомость по периодам (режим по умолчанию)", async () => {
    render(<HrPayrollView />);
    expect(screen.getByText("Начисления зарплаты")).toBeInTheDocument();

    // ведомость грузится с /api/hr/payroll/summary
    expect(await screen.findByText("2026-06")).toBeInTheDocument();
    expect(screen.getByText("2026-05")).toBeInTheDocument();
    // итог по периоду отформатирован (3 500,00)
    expect(screen.getByText(moneyText("3500"))).toBeInTheDocument();
  });

  it("пустая ведомость показывает подсказку «Ведомость пуста.»", async () => {
    fetchMock = installFetch();
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/api/hr/payroll/summary")) return jsonResponse([]);
      if (url.startsWith("/api/hr/employees")) return jsonResponse(employees);
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<HrPayrollView />);
    expect(await screen.findByText("Ведомость пуста.")).toBeInTheDocument();
  });

  it("ошибка загрузки ведомости показывает сообщение о сбое HR-модуля", async () => {
    fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/api/hr/payroll/summary")) return jsonResponse({}, false, 500);
      if (url.startsWith("/api/hr/employees")) return jsonResponse(employees);
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<HrPayrollView />);
    expect(
      await screen.findByText(/Не удалось загрузить ведомость/),
    ).toBeInTheDocument();
  });

  it("переключение на «Детально» грузит начисления и резолвит имена сотрудников", async () => {
    render(<HrPayrollView />);
    await screen.findByText("2026-06"); // дождались первичной загрузки

    fireEvent.click(screen.getByRole("button", { name: "Детально" }));

    // имена берутся из /api/hr/employees по employee_id
    expect(await screen.findByText("Иванов Иван")).toBeInTheDocument();
    expect(screen.getByText("Петрова Анна")).toBeInTheDocument();
    // суммы отформатированы, статусы переведены
    expect(screen.getByText(moneyText("1500"))).toBeInTheDocument();
    expect(screen.getByText("ожидает")).toBeInTheDocument();
    expect(screen.getByText("выплачено")).toBeInTheDocument();
  });

  it("фильтр статуса «Ожидают» перезапрашивает /api/hr/payroll?status=pending", async () => {
    render(<HrPayrollView />);
    fireEvent.click(screen.getByRole("button", { name: "Детально" }));
    await screen.findByText("Иванов Иван");

    fireEvent.click(screen.getByRole("button", { name: "Ожидают" }));

    await waitFor(() =>
      expect(fetchCalls(fetchMock).some((u) => u.includes("/api/hr/payroll?status=pending"))).toBe(
        true,
      ),
    );
  });

  it("форма начисления валидирует пустые поля, не отправляя запрос", async () => {
    render(<HrPayrollView />);
    fireEvent.click(screen.getByRole("button", { name: "+ Начислить" }));

    // без выбранного сотрудника/суммы — ошибка валидации, POST не уходит
    fireEvent.click(screen.getByRole("button", { name: "Начислить" }));
    expect(await screen.findByText("Заполните все поля")).toBeInTheDocument();
    expect(fetchCalls(fetchMock).some((u) => u.includes("/accrue"))).toBe(false);
  });

  it("успешное начисление шлёт POST /accrue с телом и закрывает форму", async () => {
    render(<HrPayrollView />);
    await screen.findByText("2026-06"); // сотрудники подгрузились для селекта

    fireEvent.click(screen.getByRole("button", { name: "+ Начислить" }));

    const form = screen.getByText("Новое начисление").closest("div") as HTMLElement;
    fireEvent.change(within(form).getByRole("combobox"), { target: { value: "1" } });
    fireEvent.change(within(form).getByPlaceholderText("1 500.00"), {
      target: { value: "1750.00" },
    });

    fireEvent.click(within(form).getByRole("button", { name: "Начислить" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/hr/payroll/accrue",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    const accrueCall = fetchMock.mock.calls.find((c) => String(c[0]).includes("/accrue"));
    const body = JSON.parse((accrueCall?.[1] as RequestInit).body as string);
    expect(body).toMatchObject({ employee_id: 1, amount_byn: "1750.00" });

    // форма закрылась после успеха
    await waitFor(() =>
      expect(screen.queryByText("Новое начисление")).not.toBeInTheDocument(),
    );
  });

  it("ошибка бэкенда при начислении показывает detail и оставляет форму открытой", async () => {
    fetchMock = installFetch({
      accrueResponse: () => jsonResponse({ detail: "Недостаточно прав" }, false, 403),
    });

    render(<HrPayrollView />);
    await screen.findByText("2026-06");

    fireEvent.click(screen.getByRole("button", { name: "+ Начислить" }));
    const form = screen.getByText("Новое начисление").closest("div") as HTMLElement;
    fireEvent.change(within(form).getByRole("combobox"), { target: { value: "1" } });
    fireEvent.change(within(form).getByPlaceholderText("1 500.00"), {
      target: { value: "900" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Начислить" }));

    expect(await screen.findByText("Недостаточно прав")).toBeInTheDocument();
    expect(screen.getByText("Новое начисление")).toBeInTheDocument(); // форма не закрылась
  });

  it("разворот периода в ведомости грузит детализацию и «Выплатить» шлёт POST /pay", async () => {
    render(<HrPayrollView />);
    const periodCell = await screen.findByText("2026-06");

    // клик по строке периода → togglePeriod → /api/hr/payroll?period=2026-06
    fireEvent.click(periodCell);

    // в детализации — имя сотрудника и кнопка «Выплатить» (у pending-строки)
    const payBtn = await screen.findByRole("button", { name: "Выплатить" });
    await waitFor(() =>
      expect(fetchCalls(fetchMock).some((u) => u.includes("period=2026-06"))).toBe(true),
    );

    fireEvent.click(payBtn);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/hr/payroll/pay",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    const payCall = fetchMock.mock.calls.find((c) => String(c[0]).includes("/payroll/pay"));
    const body = JSON.parse((payCall?.[1] as RequestInit).body as string);
    expect(body).toMatchObject({ employee_id: 1, period: "2026-06" });
  });
});
