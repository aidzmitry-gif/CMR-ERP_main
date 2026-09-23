import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

const previewPayload = {
  target_net_byn: "2000.00",
  advance_byn: "250.00",
  tax_deduction_byn: "0.00",
  other_withholding_byn: "0.00",
  income_tax_rate_pct: "13",
  employee_fszn_rate_pct: "1",
  employer_fszn_rate_pct: "34",
};

const previewResult = {
  status: "draft" as const,
  currency: "BYN" as const,
  inputs: { ...previewPayload, belgos_rate_pct: null },
  gross_byn: "2325.59",
  taxable_base_byn: "2325.59",
  income_tax_byn: "302.33",
  employee_fszn_byn: "23.26",
  employer_fszn_byn: "790.70",
  belgos_byn: null,
  net_byn: "2000.00",
  payout_byn: "1750.00",
  warnings: ["Юридические условия не проверены."],
  assumptions: ["Ставки заданы пользователем как условия сценария."],
};

const policyRow = {
  employee_id: 1, employee_name: "Иванов Иван", role: "assembler", period: "2026-10",
  status: "ready", error: null, source_ref: "Табель и наряд № 10",
  worked_days: 11, monthly_norm_hours: "168", worked_hours: "84", norm_hours: "50",
  base_byn: "1000.00", salary_byn: "500.00", bonus_byn: "340.00", gross_byn: "840.00",
  taxable_base_byn: "840.00", tax_deduction_byn: "0.00", income_tax_byn: "109.20",
  employee_fszn_byn: "8.40", other_withholding_byn: "0.00",
  employer_fszn_byn: "285.60", belgos_byn: "4.37",
  net_byn: "722.40", advance_byn: "100.00", payout_byn: "622.40",
  manual: false, manual_reason: null, manual_document_ref: null,
  policy_net_byn: "722.40", seller_gross_profit_byn: null,
  seller_opening_carry_byn: null, seller_closing_carry_byn: null,
};

// Нормализованный матчер денег: убираем пробелы-разделители (в т. ч. NBSP), decimal
// separator у ru-BY — запятая, но допускаем и точку на случай урезанного ICU.
function moneyText(target: string) {
  const normalizedTarget = target.replace(/\s/g, "").replace(".", ",");
  return (content: string) => {
    const n = content.replace(/\s/g, "");
    return n.includes(normalizedTarget);
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
  previewResponse?: () => Promise<Response>;
  policyResponse?: () => Promise<Response>;
  director?: boolean;
};

function installFetch(overrides: FetchOverrides = {}) {
  const mock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.startsWith("/api/system/access")) return jsonResponse({ current_roles: [overrides.director ? "director" : "accountant"] });
    if (url.startsWith("/api/hr/payroll/summary")) return jsonResponse(summaries);
    if (url.startsWith("/api/hr/payroll/policy-preview")) {
      return overrides.policyResponse ? overrides.policyResponse() : jsonResponse({
        status: "draft", currency: "BYN", can_manual_adjust: overrides.director === true,
        rows: [policyRow], warnings: ["Только черновик"],
      });
    }
    // Этот маршрут обязан стоять перед общим /api/hr/payroll, иначе preview примет legacy-список.
    if (url.startsWith("/api/hr/payroll/preview")) {
      return overrides.previewResponse ? overrides.previewResponse() : jsonResponse(previewResult);
    }
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

function fillPreviewForm(form: HTMLElement) {
  for (const [label, value] of Object.entries(previewPayload)) {
    const labels: Record<string, string> = {
      target_net_byn: "На руки за месяц до аванса, BYN",
      advance_byn: "Аванс, BYN",
      tax_deduction_byn: "Налоговый вычет, BYN",
      other_withholding_byn: "Прочие удержания, BYN",
      income_tax_rate_pct: "Подоходный налог, %",
      employee_fszn_rate_pct: "ФСЗН работника, %",
      employer_fszn_rate_pct: "ФСЗН нанимателя, %",
    };
    fireEvent.change(within(form).getByLabelText(labels[label]), { target: { value } });
  }
}

function expectPreviewAmount(result: HTMLElement, label: string, amount: string) {
  const row = within(result).getByText(label).closest("tr");
  expect(row).not.toBeNull();
  expect(within(row as HTMLElement).getByText(moneyText(amount))).toBeInTheDocument();
}

function expectPreviewText(result: HTMLElement, label: string, value: string) {
  const row = within(result).getByText(label).closest("tr");
  expect(row).not.toBeNull();
  expect((row as HTMLElement).textContent?.replace(/\s/g, "")).toContain(value.replace(/\s/g, ""));
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
  it("строит черновую ведомость из серверного расчёта, с днями, налогами и подготовительными карточками", async () => {
    render(<HrPayrollView />);
    await screen.findByText("2026-06");
    fireEvent.click(screen.getByRole("button", { name: "Открыть черновую месячную ведомость" }));
    expect(screen.queryByRole("option", { name: "Ручная сумма директора" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Сотрудник черновика"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Категория оплаты"), { target: { value: "assembler" } });
    fireEvent.change(screen.getByLabelText("Месяц черновика"), { target: { value: "2026-10" } });
    fireEvent.click(screen.getByRole("button", { name: "Добавить строку" }));
    fireEvent.change(screen.getByLabelText("Отработано дней Иванов Иван 2026-10"), { target: { value: "11" } });
    fireEvent.change(screen.getByLabelText("Документы-основания Иванов Иван 2026-10"), { target: { value: "Табель и наряд № 10" } });
    for (const [label, value] of [
      ["Норма часов месяца", "168"], ["Часы по табелю", "84"],
      ["Выполненные нормо-часы", "50"], ["Аванс, BYN", "100"],
      ["Налоговый вычет, BYN", "0"], ["Прочие удержания, BYN", "0"],
    ]) fireEvent.change(screen.getByLabelText(`${label} Иванов Иван 2026-10`), { target: { value } });
    fireEvent.click(screen.getByRole("button", { name: "Рассчитать ведомость-черновик" }));
    await screen.findByText(/Готово 1 из 1/);
    const table = screen.getByRole("table", { name: "Месячная ведомость черновик" });
    expect(within(table).getByText("11")).toBeInTheDocument();
    expect(within(table).getByText(moneyText("500.00"))).toBeInTheDocument();
    expect(within(table).getByText(moneyText("340.00"))).toBeInTheDocument();
    expect(within(table).getByText(moneyText("722.40"))).toBeInTheDocument();
    expect(screen.getByText(/4-фонд · подготовка/)).toBeInTheDocument();
    expect(screen.getByText(/ПУ-3 · подготовка/)).toBeInTheDocument();
    expect(screen.getByText(/Сведения о доходах · подготовка/)).toBeInTheDocument();
    const call = fetchMock.mock.calls.find((item) => String(item[0]).endsWith("/payroll/policy-preview"));
    expect(call).toBeDefined();
    const payload = JSON.parse((call?.[1] as RequestInit).body as string);
    expect(payload.employees[0].months[0]).toMatchObject({
      period: "2026-10", worked_days: 11, worked_hours: "84", norm_hours: "50",
      source_ref: "Табель и наряд № 10", shipment_cost_byn: null,
    });
    expect(fetchCalls(fetchMock).some((url) => url.endsWith("/accrue") || url.endsWith("/pay"))).toBe(false);
    const printSpy = vi.spyOn(window, "print").mockImplementation(() => {});
    fireEvent.click(screen.getByRole("button", { name: "Печать месячной ведомости" }));
    const sheet = screen.getByRole("document", { name: "Печатная черновая месячная ведомость" });
    expect(within(sheet).getByText("11")).toBeInTheDocument();
    expect(within(sheet).queryByText(/перенос/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Печать листка" }));
    const slip = screen.getByRole("document", { name: "Печатный черновой расчётный листок" });
    expect(within(slip).getByText(/На руки = начислено − удержания/)).toBeInTheDocument();
    expect(within(slip).queryByText(/перенос/i)).not.toBeInTheDocument();
    await waitFor(() => expect(printSpy).toHaveBeenCalled());
  });

  it("печатает два персональных коротких листка на одном A4 без данных о переносе", async () => {
    fetchMock = installFetch({ policyResponse: () => jsonResponse({
      status: "draft", currency: "BYN", can_manual_adjust: false,
      rows: [policyRow, { ...policyRow, employee_id: 2, employee_name: "Петрова Анна", worked_days: 20,
        salary_byn: "1000.00", bonus_byn: "0.00", gross_byn: "1000.00", income_tax_byn: "130.00",
        employee_fszn_byn: "10.00", net_byn: "860.00", advance_byn: "200.00", payout_byn: "660.00" }],
      warnings: [],
    }) });
    render(<HrPayrollView />);
    await screen.findByText("2026-06");
    fireEvent.click(screen.getByRole("button", { name: "Открыть черновую месячную ведомость" }));
    fireEvent.change(screen.getByLabelText("Сотрудник черновика"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Месяц черновика"), { target: { value: "2026-10" } });
    fireEvent.click(screen.getByRole("button", { name: "Добавить строку" }));
    for (const label of ["Аванс, BYN", "Налоговый вычет, BYN", "Прочие удержания, BYN"]) {
      fireEvent.change(screen.getByLabelText(`${label} Иванов Иван 2026-10`), { target: { value: "0" } });
    }
    fireEvent.click(screen.getByRole("button", { name: "Рассчитать ведомость-черновик" }));
    await screen.findByText(/Готово 2 из 2/);
    const printSpy = vi.spyOn(window, "print").mockImplementation(() => {});
    fireEvent.click(screen.getByRole("button", { name: "Листки для выдачи · 2 на A4" }));
    const handout = screen.getByRole("document", { name: "Печатные расчётные листки для сотрудников" });
    const pages = handout.querySelectorAll(".payroll-handout-page");
    expect(pages).toHaveLength(1);
    const slips = handout.querySelectorAll(".payroll-handout-slip");
    expect(slips).toHaveLength(2);
    expect(slips[0]).toHaveAttribute("aria-label", "Расчётный листок Иванов Иван 2026-10");
    expect(slips[1]).toHaveAttribute("aria-label", "Расчётный листок Петрова Анна 2026-10");
    expect(within(slips[0] as HTMLElement).getByText(moneyText("622.40"))).toBeInTheDocument();
    expect(within(slips[1] as HTMLElement).getByText(moneyText("660.00"))).toBeInTheDocument();
    expect(within(handout).queryByText(/перенос/i)).not.toBeInTheDocument();
    await waitFor(() => expect(printSpy).toHaveBeenCalled());
  });

  it("показывает ручную сумму только при серверной роли директора", async () => {
    fetchMock = installFetch({ director: true });
    render(<HrPayrollView />);
    await waitFor(() => expect(fetchCalls(fetchMock)).toContain("/api/system/access"));
    fireEvent.click(screen.getByRole("button", { name: "Открыть черновую месячную ведомость" }));
    fireEvent.change(screen.getByLabelText("Сотрудник черновика"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Добавить строку" }));
    expect(await screen.findByRole("option", { name: "Ручная сумма директора" })).toBeInTheDocument();
  });

  it("группирует два месяца одного продавца и показывает перенос только на экране", async () => {
    const october = {
      ...policyRow, role: "seller", salary_byn: "1500.00", base_byn: "1500.00",
      bonus_byn: "0.00", gross_byn: "1500.00", net_byn: "1290.00",
      seller_gross_profit_byn: "-500.00", seller_opening_carry_byn: "0.00",
      seller_closing_carry_byn: "500.00",
    };
    const november = {
      ...october, period: "2026-11", bonus_byn: "175.00", gross_byn: "1675.00",
      net_byn: "1440.50", seller_gross_profit_byn: "4000.00",
      seller_opening_carry_byn: "500.00", seller_closing_carry_byn: "0.00",
    };
    fetchMock = installFetch({ policyResponse: () => jsonResponse({
      status: "draft", currency: "BYN", can_manual_adjust: false,
      rows: [october, november], warnings: ["Только черновик"],
    }) });
    render(<HrPayrollView />);
    await screen.findByText("2026-06");
    fireEvent.click(screen.getByRole("button", { name: "Открыть черновую месячную ведомость" }));
    fireEvent.change(screen.getByLabelText("Сотрудник черновика"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Категория оплаты"), { target: { value: "seller" } });
    for (const month of ["2026-10", "2026-11"]) {
      fireEvent.change(screen.getByLabelText("Месяц черновика"), { target: { value: month } });
      fireEvent.click(screen.getByRole("button", { name: "Добавить строку" }));
      for (const label of ["Аванс, BYN", "Налоговый вычет, BYN", "Прочие удержания, BYN"]) {
        fireEvent.change(screen.getByLabelText(`${label} Иванов Иван ${month}`), { target: { value: "0" } });
      }
    }
    fireEvent.click(screen.getByRole("button", { name: "Рассчитать ведомость-черновик" }));
    await screen.findByText(/Готово 1 из 1/);
    const call = fetchMock.mock.calls.find((item) => String(item[0]).endsWith("/payroll/policy-preview"));
    const payload = JSON.parse((call?.[1] as RequestInit).body as string);
    expect(payload.employees).toHaveLength(1);
    expect(payload.employees[0].months.map((month: { period: string }) => month.period)).toEqual(["2026-10", "2026-11"]);
    expect(moneyText("500.00")(screen.getByText(/перенос на следующий месяц/).textContent ?? "")).toBe(true);
    fireEvent.change(screen.getByLabelText("Расчётный месяц ведомости"), { target: { value: "2026-11" } });
    expect(moneyText("500.00")(screen.getByText(/входящий перенос/).textContent ?? "")).toBe(true);
    expect(within(screen.getByRole("table", { name: "Месячная ведомость черновик" })).getByText(moneyText("175.00"))).toBeInTheDocument();
  });

  it("помечает ручное исключение в печатной ведомости и не смешивает два печатных preview", async () => {
    const printSpy = vi.spyOn(window, "print").mockImplementation(() => {});
    const manualRow = {
      ...policyRow, manual: true, manual_reason: "Отдельное соглашение",
      manual_document_ref: "Приказ № 21", policy_net_byn: "722.40",
      net_byn: "800.00", payout_byn: "700.00", gross_byn: "930.23",
    };
    fetchMock = installFetch({ director: true, policyResponse: () => jsonResponse({
      status: "draft", currency: "BYN", can_manual_adjust: true,
      rows: [manualRow], warnings: ["Только черновик"],
    }) });
    render(<HrPayrollView />);
    await screen.findByText("2026-06");
    fireEvent.click(screen.getByRole("button", { name: "Открыть черновую месячную ведомость" }));
    fireEvent.change(screen.getByLabelText("Сотрудник черновика"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Добавить строку" }));
    for (const label of ["Аванс, BYN", "Налоговый вычет, BYN", "Прочие удержания, BYN"]) {
      fireEvent.change(screen.getByLabelText(`${label} Иванов Иван ${new Date().toISOString().slice(0, 7)}`), { target: { value: "0" } });
    }
    fireEvent.click(screen.getByRole("button", { name: "Рассчитать ведомость-черновик" }));
    await screen.findByText(/Готово 1 из 1/);
    fireEvent.click(screen.getByRole("button", { name: "Печать месячной ведомости" }));
    const sheet = screen.getByRole("document", { name: "Печатная черновая месячная ведомость" });
    expect(within(sheet).getByText(/Ручные исключения/)).toHaveTextContent("Приказ № 21");
    expect(within(sheet).queryByText(/перенос/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Рассчитать от суммы «на руки»" }));
    const oldForm = screen.getByRole("region", { name: "Черновой расчёт от суммы на руки" });
    fillPreviewForm(oldForm);
    fireEvent.click(within(oldForm).getByRole("button", { name: "Рассчитать черновик" }));
    await screen.findByRole("document", { name: "Печатный черновик расчёта зарплаты" });
    await waitFor(() => expect(screen.queryByRole("document", { name: "Печатная черновая месячная ведомость" })).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Печать месячной ведомости" }));
    await waitFor(() => expect(screen.queryByRole("document", { name: "Печатный черновик расчёта зарплаты" })).not.toBeInTheDocument());
    expect(screen.getByRole("document", { name: "Печатная черновая месячная ведомость" })).toBeInTheDocument();
    await waitFor(() => expect(printSpy).toHaveBeenCalled());
  });
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

  it("рассчитывает отдельный черновик от суммы на руки без accrue/pay и очищает его при закрытии", async () => {
    render(<HrPayrollView />);
    await screen.findByText("2026-06");

    fireEvent.click(screen.getByRole("button", { name: "Рассчитать от суммы «на руки»" }));
    const form = screen.getByRole("region", { name: "Черновой расчёт от суммы на руки" });
    fillPreviewForm(form);
    fireEvent.click(within(form).getByRole("button", { name: "Рассчитать черновик" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/hr/payroll/preview",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    const previewCall = fetchMock.mock.calls.find((c) => String(c[0]).includes("/payroll/preview"));
    expect(JSON.parse((previewCall?.[1] as RequestInit).body as string)).toEqual({
      ...previewPayload,
      belgos_rate_pct: null,
    });

    const result = await screen.findByRole("region", { name: "Результат чернового расчёта" });
    expectPreviewAmount(result, "Начислено, BYN", "2325.59");
    expectPreviewAmount(result, "Подоходный налог, BYN", "302.33");
    expectPreviewAmount(result, "ФСЗН работника, BYN", "23.26");
    expectPreviewAmount(result, "ФСЗН нанимателя, BYN", "790.70");
    expectPreviewAmount(result, "На руки за месяц, BYN", "2000.00");
    expectPreviewAmount(result, "Остаток к выплате после аванса, BYN", "1750.00");
    expect(within(result).getByText("Неизвестно")).toBeInTheDocument();
    expect(within(result).getByText("Юридические условия не проверены.")).toBeInTheDocument();
    expect(within(result).getByText("Ставки заданы пользователем как условия сценария.")).toBeInTheDocument();
    expect(fetchCalls(fetchMock).some((url) => url.includes("/accrue") || url.endsWith("/pay"))).toBe(false);

    fireEvent.click(within(form).getByRole("button", { name: "Закрыть" }));
    expect(screen.queryByRole("region", { name: "Черновой расчёт от суммы на руки" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Рассчитать от суммы «на руки»" }));
    expect(screen.queryByRole("region", { name: "Результат чернового расчёта" })).not.toBeInTheDocument();
  });

  it("при 1440px без preview не скрывает обычную печать и резервирует место для ChatsPanel", async () => {
    const printSpy = vi.spyOn(window, "print").mockImplementation(() => {});
    const initialWidth = window.innerWidth;
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1440 });
    render(<HrPayrollView />);
    await screen.findByText("2026-06");

    const main = screen.getByRole("main");
    expect(main).toHaveClass("pr-24", "print:pr-6");
    expect(main).not.toHaveClass("print:hidden");
    expect(screen.queryByRole("button", { name: "Печать черновика" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("payroll-preview-print-css")).not.toBeInTheDocument();
    expect(printSpy).not.toHaveBeenCalled();
    Object.defineProperty(window, "innerWidth", { configurable: true, value: initialWidth });
  });

  it("печатает существующий preview без нового POST и показывает тот же самостоятельный документ", async () => {
    const printSpy = vi.spyOn(window, "print").mockImplementation(() => {});
    render(<HrPayrollView />);
    await screen.findByText("2026-06");
    fireEvent.click(screen.getByRole("button", { name: "Рассчитать от суммы «на руки»" }));
    const form = screen.getByRole("region", { name: "Черновой расчёт от суммы на руки" });
    fillPreviewForm(form);
    fireEvent.click(within(form).getByRole("button", { name: "Рассчитать черновик" }));

    await screen.findByRole("region", { name: "Результат чернового расчёта" });
    const previewPosts = () => fetchCalls(fetchMock).filter((url) => url.includes("/payroll/preview"));
    expect(previewPosts()).toHaveLength(1);
    expect(screen.getByRole("main")).toHaveClass("print:hidden");

    const printed = screen.getByRole("document", { name: "Печатный черновик расчёта зарплаты" });
    expect(printed).toHaveClass("hidden", "print:block");
    expect(within(printed).getByText("Черновик — не ведомость и не платёжный документ.")).toBeInTheDocument();
    expectPreviewAmount(printed, "Целевая сумма на руки до аванса, BYN", "2000.00");
    expectPreviewAmount(printed, "Аванс, BYN", "250.00");
    expectPreviewAmount(printed, "Налоговый вычет, BYN", "0.00");
    expectPreviewAmount(printed, "Прочие удержания, BYN", "0.00");
    expectPreviewText(printed, "Подоходный налог, %", "13,00%");
    expectPreviewText(printed, "ФСЗН работника, %", "1,00%");
    expectPreviewText(printed, "ФСЗН нанимателя, %", "34,00%");
    expectPreviewText(printed, "Белгосстрах, %", "Не задано / неизвестно");
    expectPreviewAmount(printed, "Начислено, BYN", "2325.59");
    expectPreviewAmount(printed, "Подоходный налог, BYN", "302.33");
    expectPreviewAmount(printed, "ФСЗН работника, BYN", "23.26");
    expectPreviewAmount(printed, "ФСЗН нанимателя, BYN", "790.70");
    expectPreviewAmount(printed, "На руки за месяц, BYN", "2000.00");
    expectPreviewAmount(printed, "Остаток к выплате после аванса, BYN", "1750.00");
    expect(within(printed).getByText("Неизвестно")).toBeInTheDocument();
    expect(within(printed).getByText("Юридические условия не проверены.")).toBeInTheDocument();
    expect(within(printed).getByText("Ставки заданы пользователем как условия сценария.")).toBeInTheDocument();

    const css = screen.getByTestId("payroll-preview-print-css").textContent ?? "";
    expect(css).toContain("@media print");
    expect(css).toContain("html, body { background: #fff !important; }");
    expect(css).toContain("body * { visibility: hidden !important; }");
    expect(css).toContain("[data-payroll-preview-print], [data-payroll-preview-print] * { visibility: visible !important; }");
    expect(css).toContain("overflow: visible !important;");
    expect(css).toContain("color: #000 !important;");
    expect(css).toContain("background: #fff !important;");
    expect(css).toContain("border-color: #000 !important;");

    fireEvent.click(within(form).getByRole("button", { name: "Печать черновика" }));
    expect(printSpy).toHaveBeenCalledTimes(1);
    expect(previewPosts()).toHaveLength(1);
  });

  it("отличает явную нулевую ставку Белгосстраха от неизвестной и очищает preview при смене формы", async () => {
    fetchMock = installFetch({
      previewResponse: () => jsonResponse({
        ...previewResult,
        inputs: { ...previewResult.inputs, belgos_rate_pct: "0" },
        belgos_byn: "0.00",
      }),
    });

    render(<HrPayrollView />);
    await screen.findByText("2026-06");
    fireEvent.click(screen.getByRole("button", { name: "Рассчитать от суммы «на руки»" }));
    const form = screen.getByRole("region", { name: "Черновой расчёт от суммы на руки" });
    fillPreviewForm(form);
    fireEvent.change(within(form).getByLabelText("Белгосстрах, % (необязательно)"), {
      target: { value: "0" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Рассчитать черновик" }));

    const result = await screen.findByRole("region", { name: "Результат чернового расчёта" });
    expectPreviewAmount(result, "Белгосстрах, BYN", "0.00");
    const previewCall = fetchMock.mock.calls.find((c) => String(c[0]).includes("/payroll/preview"));
    expect(JSON.parse((previewCall?.[1] as RequestInit).body as string)).toMatchObject({ belgos_rate_pct: "0" });

    fireEvent.click(screen.getByRole("button", { name: "+ Начислить" }));
    fireEvent.click(screen.getByRole("button", { name: "Рассчитать от суммы «на руки»" }));
    expect(screen.queryByRole("region", { name: "Результат чернового расчёта" })).not.toBeInTheDocument();
  });

  it("не подставляет нули в черновик и нормализует detail для 422", async () => {
    render(<HrPayrollView />);
    await screen.findByText("2026-06");
    fireEvent.click(screen.getByRole("button", { name: "Рассчитать от суммы «на руки»" }));
    const form = screen.getByRole("region", { name: "Черновой расчёт от суммы на руки" });

    fireEvent.click(within(form).getByRole("button", { name: "Рассчитать черновик" }));
    expect(await screen.findByText(/Нули не подставляются автоматически/)).toBeInTheDocument();
    expect(fetchCalls(fetchMock).some((url) => url.includes("/payroll/preview"))).toBe(false);

    fetchMock = installFetch({
      previewResponse: () => jsonResponse({
        detail: [{ loc: ["body", "income_tax_rate_pct"], msg: "Ставка должна быть подтверждена" }],
      }, false, 422),
    });
    fillPreviewForm(form);
    fireEvent.click(within(form).getByRole("button", { name: "Рассчитать черновик" }));

    expect(await screen.findByText("income_tax_rate_pct: Ставка должна быть подтверждена")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Результат чернового расчёта" })).not.toBeInTheDocument();
  });

  it("игнорирует ответ preview, устаревший после изменения условий", async () => {
    let resolvePreview: ((response: Response) => void) | undefined;
    fetchMock = installFetch({
      previewResponse: () => new Promise<Response>((resolve) => { resolvePreview = resolve; }),
    });

    render(<HrPayrollView />);
    await screen.findByText("2026-06");
    fireEvent.click(screen.getByRole("button", { name: "Рассчитать от суммы «на руки»" }));
    const form = screen.getByRole("region", { name: "Черновой расчёт от суммы на руки" });
    fillPreviewForm(form);
    fireEvent.click(within(form).getByRole("button", { name: "Рассчитать черновик" }));
    await waitFor(() => expect(resolvePreview).toBeTypeOf("function"));

    fireEvent.change(within(form).getByLabelText("На руки за месяц до аванса, BYN"), {
      target: { value: "2100.00" },
    });
    await act(async () => {
      resolvePreview?.({ ok: true, status: 200, json: async () => previewResult } as Response);
    });

    expect(screen.queryByRole("region", { name: "Результат чернового расчёта" })).not.toBeInTheDocument();
    expect(within(form).getByRole("button", { name: "Рассчитать черновик" })).toBeEnabled();
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
    expect(body).toMatchObject({ employee_id: 1, period: "2026-06", entry_id: 10 });
  });
});
