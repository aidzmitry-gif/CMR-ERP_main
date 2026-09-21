import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FinanceView } from "@/components/erp/finance-view";

// FinanceView ходит в backend через глобальный fetch (useFetch + прямые POST).
// Мокаем fetch и маршрутизируем ответы по URL — компонент тестируем изолированно.
// Ключи матчятся по вхождению в URL, от длинного к короткому (иначе "payments"
// перехватит "payments/5/allocations", а "cashflow" — "cashflow-forecast").
type Responder = unknown | "error";
let responders: Record<string, Responder>;

function respond(url: string): { ok: boolean; status: number; json: () => Promise<unknown> } {
  const keys = Object.keys(responders).sort((a, b) => b.length - a.length);
  for (const k of keys) {
    if (url.includes(k)) {
      const r = responders[k];
      if (r === "error") return { ok: false, status: 500, json: () => Promise.resolve(null) };
      return { ok: true, status: 200, json: () => Promise.resolve(r) };
    }
  }
  return { ok: true, status: 200, json: () => Promise.resolve(null) };
}

const fetchMock = vi.fn((input: unknown) => Promise.resolve(respond(String(input))));

const SUMMARY = {
  currency: "BYN",
  margin: { revenue: "50000.00", landed: "30000.00", freight: "2000.00", gross: "18000.00", pct: 36 },
  cash: {
    inflow: "12000.00",
    outflow: "5000.00",
    net: "7000.00",
    received: "12000.00",
    pending_receivable: "9000.00",
    freight_refund: "0.00",
  },
  costs: [
    { kind: "freight", label: "Фрахт", amount: "2000.00" },
    { kind: "landed", label: "Себестоимость", amount: "30000.00" },
  ],
};

const LEDGER_REPORT = {
  organization_id: 7,
  from: "2026-09-01",
  to: "2026-09-30",
  status: "preliminary",
  pending_documents: 0,
  review_items: [],
  pnl: { income: "20.00", expenses: "3.33", profit: "16.67" },
  pnl_movements: [],
  balance: { assets: "31.67", liabilities: "14.00", equity: "0.00", current_result: "16.67", difference: "1.00" },
  balance_movements: [
    { entry_id: 9, source: "opening-import", date: "2026-09-01", account: "51", title: "Банк", line_id: 10, currency: "BYN", side: "debit", amount: "15.00", dimensions: {}, category: "asset", period_bucket: "opening" },
  ],
  cashflow_ledger: {
    opening: "50.00", external_inflow: "100.00", external_outflow: "40.00", external_net: "60.00",
    internal_net: "0.00", internal_count: 0, unclassified_inflow: "0.00", unclassified_outflow: "0.00",
    unclassified_net: "0.00", unclassified_count: 0, opening_adjustment_net: "0.00", opening_adjustment_count: 0,
    closing: "110.00",
    activities: {
      operating: { inflow: "100.00", outflow: "40.00", net: "60.00" },
      investing: { inflow: "0.00", outflow: "0.00", net: "0.00" },
      financing: { inflow: "0.00", outflow: "0.00", net: "0.00" },
    },
  },
  cash_movements: [],
};

function ledgerResponses() {
  responders["accounting/organizations"] = [{ id: 7, name: "Организация", unp: "123" }];
  responders["accounting/organizations/7/reports"] = LEDGER_REPORT;
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockClear();
  // Безопасные значения по умолчанию для всех эндпоинтов (summary-таб стреляет на маунте).
  responders = {
    "finance/summary": SUMMARY,
    "finance/payments": [],
    "finance/aging": { as_of: "2026-07-18", currency: "BYN", ar: { buckets: {}, total: "0.00" }, ap: { buckets: {}, total: "0.00" } },
    "finance/cashflow-forecast": { as_of: "2026-07-18", currency: "BYN", opening_balance: "0.00", weeks: [], not_dated: { inflow: "0.00", outflow: "0.00" } },
    "finance/cashflow": { period_from: null, period_to: null, currency: "BYN", inflows: "0.00", outflows: "0.00", net_cashflow: "0.00", bank_balance: null, breakdown: {} },
    "finance/pnl": null,
    "finance/balance-sheet": null,
    "finance/reconcile-1c": { as_of: "2026-07-18", source: "1c", source_available: false, matched: [], only_in_erp: [], only_in_1c: [] },
    "finance/bank-accounts": [],
    "finance/margin/by-deal": { currency: "BYN", items: [] },
    "finance/margin/by-counterparty": { currency: "BYN", items: [] },
  };
});

afterEach(() => vi.unstubAllGlobals());

// ru-RU разделитель разрядов — неразрывный пробел; \s покрывает его в regexp.
const byn = (whole: string) => new RegExp(`${whole.replace(/\B(?=(\d{3})+(?!\d))/g, "\\s")}\\sBYN`);

describe("FinanceView", () => {
  it("рендерит заголовок и все вкладки финансов", () => {
    render(<FinanceView />);
    expect(screen.getByRole("heading", { name: "Финансы" })).toBeInTheDocument();
    for (const label of ["Касса и маржа", "Платежи", "Aging", "Cash-flow", "P&L", "Баланс", "Сверка 1С"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
  });

  it("вкладка «Касса и маржа» показывает кассу, фактическую маржу и затраты по типам", async () => {
    render(<FinanceView />);
    expect(await screen.findByText("Касса (ДДС-lite)")).toBeInTheDocument();

    // касса: поступления/расходы/сальдо/к поступлению + суммы из фикстуры
    expect(screen.getByText("Поступления")).toBeInTheDocument();
    expect(screen.getByText(byn("12000"))).toBeInTheDocument(); // inflow
    expect(screen.getByText(byn("9000"))).toBeInTheDocument(); // pending_receivable

    // маржа: заголовок валовой прибыли несёт процент из бэка
    expect(screen.getByText("Фактическая маржа (по фактам)")).toBeInTheDocument();
    expect(screen.getByText(byn("50000"))).toBeInTheDocument(); // revenue
    expect(screen.getByText(/Валовая прибыль · 36\.0%/)).toBeInTheDocument();

    // затраты по типам — строки из costs[] (30000 встречается и в марже landed, и в затратах)
    expect(screen.getByText("Себестоимость")).toBeInTheDocument();
    expect(screen.getAllByText(byn("30000")).length).toBeGreaterThan(0);
  });

  it("ошибка загрузки сводки показывает сообщение «нет связи», а не пустой экран", async () => {
    responders["finance/summary"] = "error";
    render(<FinanceView />);
    expect(await screen.findByText(/Нет связи с финансовым модулем/)).toBeInTheDocument();
    // при revenue=0 подсказки быть не должно — потому что до маржи мы не дошли
    expect(screen.queryByText("Касса (ДДС-lite)")).not.toBeInTheDocument();
  });

  it("нулевая выручка в сводке показывает честную подсказку про отсутствие маржи", async () => {
    responders["finance/summary"] = {
      ...SUMMARY,
      margin: { revenue: "0.00", landed: "0.00", freight: "0.00", gross: "0.00", pct: null },
    };
    render(<FinanceView />);
    expect(await screen.findByText(/Выручки по фактам пока нет/)).toBeInTheDocument();
  });

  it("переключение на «Платежи» с пустым списком показывает пустое состояние", async () => {
    render(<FinanceView />);
    await screen.findByText("Касса (ДДС-lite)");

    fireEvent.click(screen.getByRole("button", { name: "Платежи" }));
    expect(await screen.findByText(/платежи пока пусто/)).toBeInTheDocument();
  });

  it("на вкладке «Платежи» кнопка «Зафиксировать поступление» открывает форму и постит allocation", async () => {
    responders["finance/payments"] = [
      {
        id: 5,
        ref: "Счёт №77",
        amount: "1500.00",
        status: "pending",
        kind: "receivable",
        due_date: "2026-08-01",
        paid_at: null,
        deal_id: 42,
        counterparty_ref: null,
        outstanding: "1500.00",
        is_overdue: false,
      },
    ];
    render(<FinanceView />);
    await screen.findByText("Касса (ДДС-lite)");
    fireEvent.click(screen.getByRole("button", { name: "Платежи" }));

    // строка платежа отрисовалась
    expect(await screen.findByText("Счёт №77")).toBeInTheDocument();

    // открываем форму фиксации поступления
    fireEvent.click(screen.getByRole("button", { name: /Зафиксировать поступление/ }));
    const heading = await screen.findByText(/Поступление по/);
    expect(heading).toBeInTheDocument();

    // сумма предзаполнена остатком; жмём «Зафиксировать»
    const input = document.querySelector('input[type="number"]') as HTMLInputElement;
    expect(input.value).toBe("1500.00");
    fireEvent.click(screen.getByRole("button", { name: "Зафиксировать" }));

    await waitFor(() => {
      const posted = fetchMock.mock.calls.find(
        ([url, opts]) =>
          String(url).includes("/payments/5/allocations") &&
          (opts as RequestInit | undefined)?.method === "POST",
      );
      expect(posted).toBeTruthy();
      expect(String((posted?.[1] as RequestInit).body)).toContain("1500");
    });
  });

  it("валидация: allocation с суммой 0 не постит на бэкенд и показывает ошибку", async () => {
    responders["finance/payments"] = [
      {
        id: 8,
        ref: "Счёт №8",
        amount: "0.00",
        status: "pending",
        kind: "receivable",
        due_date: null,
        paid_at: null,
        deal_id: null,
        counterparty_ref: null,
        outstanding: "0.00",
        is_overdue: false,
      },
    ];
    render(<FinanceView />);
    await screen.findByText("Касса (ДДС-lite)");
    fireEvent.click(screen.getByRole("button", { name: "Платежи" }));
    await screen.findByText("Счёт №8");

    fireEvent.click(screen.getByRole("button", { name: /Зафиксировать поступление/ }));
    // остаток 0 → предзаполнено "0"; клик «Зафиксировать» отбивается валидацией
    fireEvent.click(await screen.findByRole("button", { name: "Зафиксировать" }));

    expect(await screen.findByText("Сумма должна быть > 0")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).includes("/allocations")),
    ).toBe(false);
  });

  it("вкладка «Баланс» монтирует отчёт бухгалтерской книги, а не legacy balance-sheet", async () => {
    ledgerResponses();
    render(<FinanceView />);
    await screen.findByText("Касса (ДДС-lite)");
    fireEvent.click(screen.getByRole("button", { name: "Баланс" }));

    await screen.findByRole("option", { name: "Организация · 123" });
    fireEvent.change(screen.getByLabelText("Организация баланса"), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText("Начало периода баланса"), { target: { value: "2026-09-01" } });
    fireEvent.change(screen.getByLabelText("Конец периода баланса"), { target: { value: "2026-09-30" } });
    fireEvent.click(screen.getByRole("button", { name: "Применить" }));

    expect(await screen.findByText("31.67 BYN")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Расхождение баланса: 1.00 BYN");
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/api/finance/balance-sheet"))).toBe(false);
  });

  it("вкладка «P&L» монтирует отчёт бухгалтерской книги, а не legacy P&L", async () => {
    ledgerResponses();
    render(<FinanceView />);
    await screen.findByText("Касса (ДДС-lite)");
    fireEvent.click(screen.getByRole("button", { name: "P&L" }));

    await screen.findByRole("option", { name: "Организация · 123" });
    fireEvent.change(screen.getByLabelText("Организация P&L"), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText("Начало периода P&L"), { target: { value: "2026-09-01" } });
    fireEvent.change(screen.getByLabelText("Конец периода P&L"), { target: { value: "2026-09-30" } });
    fireEvent.click(screen.getByRole("button", { name: "Применить" }));

    expect(await screen.findByText("16.67 BYN")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/api/finance/pnl"))).toBe(false);
  });

  it("вкладка «Сверка 1С» без источника показывает «сверка не настроена»", async () => {
    render(<FinanceView />);
    await screen.findByText("Касса (ДДС-lite)");
    fireEvent.click(screen.getByRole("button", { name: "Сверка 1С" }));

    expect(await screen.findByText(/Сверка с 1С не настроена/)).toBeInTheDocument();
  });

  it("вкладка «Aging» с ненулевыми остатками рендерит корзины дебиторки и кредиторки", async () => {
    responders["finance/aging"] = {
      as_of: "2026-07-18",
      currency: "BYN",
      ar: { buckets: { current: "5000.00", "90+": "1000.00" }, total: "6000.00" },
      ap: { buckets: { "1-30": "2000.00" }, total: "2000.00" },
    };
    render(<FinanceView />);
    await screen.findByText("Касса (ДДС-lite)");
    fireEvent.click(screen.getByRole("button", { name: "Aging" }));

    expect(await screen.findByText(/Дебиторка \(AR\)/)).toBeInTheDocument();
    expect(screen.getByText(/Кредиторка \(AP\)/)).toBeInTheDocument();
    // подпись критических корзин присутствует
    expect(screen.getAllByText("90+ дн.").length).toBeGreaterThan(0);
  });

  it("сводка: компенсация по претензии показывает уменьшение себестоимости, а платёж-отток рендерится с минусом", async () => {
    responders["finance/summary"] = {
      ...SUMMARY,
      margin: { ...SUMMARY.margin, claim_refund: "500.00" },
    };
    responders["finance/payments"] = [
      {
        id: 9,
        ref: "Фрахт №3",
        amount: "-300.00",
        status: "paid",
        kind: "freight",
        due_date: null,
        paid_at: "2026-07-01",
        deal_id: null,
        counterparty_ref: null,
        outstanding: null,
        is_overdue: null,
      },
    ];
    render(<FinanceView />);
    expect(await screen.findByText(/Компенсация по претензии/)).toBeInTheDocument();
    expect(screen.getByText(byn("500"))).toBeInTheDocument();
    // freight — отток (isInflow=false для не-receivable) → минус-строка и сумма 300 в таблице движения платежей
    expect(await screen.findByText("Фрахт №3")).toBeInTheDocument();
    expect(screen.getByText(byn("300"))).toBeInTheDocument();
  });

  it("вкладка «Cash-flow» с данными рендерит недели и «не датировано»", async () => {
    responders["finance/cashflow-forecast"] = {
      as_of: "2026-07-19",
      currency: "BYN",
      opening_balance: "1000.00",
      weeks: [
        { week_start: "2026-07-14", inflow: "2000.00", outflow: "500.00", net: "1500.00", cumulative: "2500.00" },
      ],
      not_dated: { inflow: "100.00", outflow: "50.00" },
    };
    render(<FinanceView />);
    await screen.findByText("Касса (ДДС-lite)");
    fireEvent.click(screen.getByRole("button", { name: "Cash-flow" }));

    expect(await screen.findByText("2026-07-14")).toBeInTheDocument();
    expect(screen.getByText(byn("1000"))).toBeInTheDocument(); // opening_balance
    expect(screen.getByText(/\+.*2\s?000.*BYN/)).toBeInTheDocument(); // inflow week
    expect(screen.getByText(byn("2500"))).toBeInTheDocument(); // cumulative
  });

  it("вкладка «Маржа» рендерит строки по сделкам и «не атрибутировано» для контрагентов", async () => {
    responders["finance/margin/by-deal"] = {
      currency: "BYN",
      items: [{ key: 42, revenue: "10000.00", landed: "6000.00", freight: "300.00", gross: "3700.00", pct: 37 }],
    };
    responders["finance/margin/by-counterparty"] = {
      currency: "BYN",
      items: [{ key: null, revenue: "500.00", landed: "200.00", freight: "0.00", gross: "300.00", pct: null }],
    };
    render(<FinanceView />);
    await screen.findByText("Касса (ДДС-lite)");
    fireEvent.click(screen.getByRole("button", { name: "Маржа" }));

    expect(await screen.findByText("Маржа по сделкам")).toBeInTheDocument();
    expect(screen.getByText("#42")).toBeInTheDocument();
    expect(screen.getByText(byn("10000"))).toBeInTheDocument();
    expect(screen.getByText(/37\.0%/)).toBeInTheDocument();

    expect(screen.getByText("Маржа по контрагентам")).toBeInTheDocument();
    expect(screen.getByText("Не атрибутировано")).toBeInTheDocument();
  });

  it("сходимость маржи (ReconcileDealCard): проверка совпадает и показывает «совпадает»", async () => {
    responders["finance/margin/reconcile-deal"] = {
      deal_id: 42,
      finance_landed: "6000.00",
      facade_landed: "6000.00",
      delta: "0.00",
      revenue: "10000.00",
      gross_finance: "3700.00",
      level: "sku",
      source_facade_available: true,
      currency: "BYN",
    };
    render(<FinanceView />);
    await screen.findByText("Касса (ДДС-lite)");
    fireEvent.click(screen.getByRole("button", { name: "Маржа" }));
    await screen.findByText("Сходимость маржи finance ↔ landed-фасад");

    const dealInput = screen.getByPlaceholderText("42");
    fireEvent.change(dealInput, { target: { value: "42" } });
    fireEvent.click(screen.getByRole("button", { name: "Проверить" }));

    expect(await screen.findByText(/Совпадает: проводки finance/)).toBeInTheDocument();
    // finance_landed И facade_landed оба 6000 (равны) → два совпадающих узла
    expect(screen.getAllByText(byn("6000")).length).toBe(2);
  });

  it("сходимость маржи: расхождение Δ≠0 показывает предупреждение о перепосчёте", async () => {
    responders["finance/margin/reconcile-deal"] = {
      deal_id: 7,
      finance_landed: "6000.00",
      facade_landed: "6500.00",
      delta: "500.00",
      revenue: "10000.00",
      gross_finance: "3700.00",
      level: "sku",
      source_facade_available: true,
      currency: "BYN",
    };
    render(<FinanceView />);
    await screen.findByText("Касса (ДДС-lite)");
    fireEvent.click(screen.getByRole("button", { name: "Маржа" }));
    fireEvent.change(await screen.findByPlaceholderText("42"), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Проверить" }));

    expect(await screen.findByText(/Δ ≠ 0. Перепосчитать landed/)).toBeInTheDocument();
  });

  it("сходимость маржи: ошибка сети показывает «не удалось получить сверку»", async () => {
    responders["finance/margin/reconcile-deal"] = "error";
    render(<FinanceView />);
    await screen.findByText("Касса (ДДС-lite)");
    fireEvent.click(screen.getByRole("button", { name: "Маржа" }));
    fireEvent.change(await screen.findByPlaceholderText("42"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Проверить" }));

    expect(await screen.findByText(/Не удалось получить сверку/)).toBeInTheDocument();
  });

  it("вкладка «ДДС» монтирует отчёт бухгалтерской книги, а не legacy ДДС", async () => {
    ledgerResponses();
    render(<FinanceView />);
    await screen.findByText("Касса (ДДС-lite)");
    fireEvent.click(screen.getByRole("button", { name: "ДДС" }));

    await screen.findByRole("option", { name: "Организация · 123" });
    fireEvent.change(screen.getByLabelText("Организация ДДС"), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText("Начало периода ДДС"), { target: { value: "2026-09-01" } });
    fireEvent.change(screen.getByLabelText("Конец периода ДДС"), { target: { value: "2026-09-30" } });
    fireEvent.click(screen.getByRole("button", { name: "Применить" }));

    expect(await screen.findByText("60.00 BYN")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/api/finance/cashflow"))).toBe(false);
  });

  it("вкладка «Сверка 1С» с источником показывает совпавшие и расхождения по сторонам", async () => {
    responders["finance/reconcile-1c"] = {
      as_of: "2026-07-19",
      source: "1c",
      source_available: true,
      matched: [{ ref: "П-1", amount: "100.00", counterparty_ref: "192766048" }],
      only_in_erp: [{ ref: "П-2", amount: "50.00", counterparty_ref: null }],
      only_in_1c: [{ ref: null, amount: "75.00", counterparty_ref: null }],
    };
    render(<FinanceView />);
    await screen.findByText("Касса (ДДС-lite)");
    fireEvent.click(screen.getByRole("button", { name: "Сверка 1С" }));

    expect(await screen.findByText("П-1")).toBeInTheDocument();
    expect(screen.getByText("П-2")).toBeInTheDocument();
    expect(screen.getByText(/Совпало · 1/)).toBeInTheDocument();
    expect(screen.getByText(/Только в ERP · 1/)).toBeInTheDocument();
    expect(screen.getByText(/Только в 1С · 1/)).toBeInTheDocument();
  });

  it("вкладка «Сверка 1С» показывает причину отсутствия проверенного источника", async () => {
    responders["finance/reconcile-1c"] = {
      as_of: "2026-07-19",
      source: "1c",
      source_available: false,
      source_reason: "Платёжный OData-адаптер ещё не проверен",
      matched: [], only_in_erp: [], only_in_1c: [],
    };
    render(<FinanceView />);
    await screen.findByText("Касса (ДДС-lite)");
    fireEvent.click(screen.getByRole("button", { name: "Сверка 1С" }));
    expect(await screen.findByText(/Платёжный OData-адаптер ещё не проверен/)).toBeInTheDocument();
  });

  it("вкладка «Календарь» позволяет завести счёт и показывает пустой горизонт без платежей", async () => {
    responders["finance/bank-accounts"] = [
      { id: 1, code: "main", title: "Расчётный", currency: "BYN", opening_balance: "0.00", opening_at: null, is_active: true },
    ];
    responders["finance/cashflow-forecast"] = {
      as_of: "2026-07-19",
      currency: "BYN",
      mode: "day",
      opening_balance: "0.00",
      weeks: [],
      buckets: [],
      not_dated: { inflow: "0.00", outflow: "0.00" },
    };
    render(<FinanceView />);
    await screen.findByText("Касса (ДДС-lite)");
    fireEvent.click(screen.getByRole("button", { name: "Календарь" }));

    expect(await screen.findByText(/main · Расчётный/)).toBeInTheDocument();
    expect(await screen.findByText("На горизонте нет ни одного датированного платежа.")).toBeInTheDocument();

    // Открываем форму заведения счёта и постим
    fireEvent.click(screen.getByRole("button", { name: "+ Завести счёт" }));
    fireEvent.change(screen.getByPlaceholderText("main"), { target: { value: "alfa" } });
    fireEvent.change(screen.getByPlaceholderText("Расчётный счёт BYN"), { target: { value: "Альфа BYN" } });
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));

    await waitFor(() => {
      const posted = fetchMock.mock.calls.find(
        ([url, opts]) =>
          String(url).includes("/bank-accounts") &&
          (opts as RequestInit | undefined)?.method === "POST",
      );
      expect(posted).toBeTruthy();
      expect(String((posted?.[1] as RequestInit).body)).toContain("alfa");
    });
  });

  it("форма счёта: пустые код/название не постятся и показывают ошибку валидации", async () => {
    render(<FinanceView />);
    await screen.findByText("Касса (ДДС-lite)");
    fireEvent.click(screen.getByRole("button", { name: "Календарь" }));

    fireEvent.click(await screen.findByRole("button", { name: "+ Завести счёт" }));
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));

    expect(await screen.findByText("Код и название обязательны")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).includes("/bank-accounts") && String(url).includes("POST")),
    ).toBe(false);
  });

  it("вкладка «P&L» показывает ошибку доступа к бухгалтерской книге", async () => {
    responders["accounting/organizations"] = [{ id: 7, name: "Организация", unp: "123" }];
    responders["accounting/organizations/7/reports"] = "error";
    render(<FinanceView />);
    await screen.findByText("Касса (ДДС-lite)");
    fireEvent.click(screen.getByRole("button", { name: "P&L" }));

    await screen.findByRole("option", { name: "Организация · 123" });
    fireEvent.change(screen.getByLabelText("Организация P&L"), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText("Начало периода P&L"), { target: { value: "2026-09-01" } });
    fireEvent.change(screen.getByLabelText("Конец периода P&L"), { target: { value: "2026-09-30" } });
    fireEvent.click(screen.getByRole("button", { name: "Применить" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить P&L бухгалтерской книги");
  });

  it("вкладка «Баланс» показывает ошибку при сбое сети", async () => {
    responders["accounting/organizations"] = [{ id: 7, name: "Организация", unp: "123" }];
    responders["accounting/organizations/7/reports"] = "error";
    render(<FinanceView />);
    await screen.findByText("Касса (ДДС-lite)");
    fireEvent.click(screen.getByRole("button", { name: "Баланс" }));

    await screen.findByRole("option", { name: "Организация · 123" });
    fireEvent.change(screen.getByLabelText("Организация баланса"), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText("Начало периода баланса"), { target: { value: "2026-09-01" } });
    fireEvent.change(screen.getByLabelText("Конец периода баланса"), { target: { value: "2026-09-30" } });
    fireEvent.click(screen.getByRole("button", { name: "Применить" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось загрузить баланс бухгалтерской книги");
  });
});
