import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { FinanceLedgerCashflow, cashflowCsv } from "./finance-ledger-cashflow";

const context = { configuration: "AIOS_SELLER_UNP", organization: { id: 7, name: "Компания установки", unp: "987654321" } };
const report = { trial_balance: [{ account: "51", title: "Банк", off_balance: false, currency: "BYN", dimensions: {}, opening: "0.00", debit: "20.00", credit: "0.00", closing: "20.00" }], organization_id: 7, from: "2026-09-01", to: "2026-09-30", status: "preliminary", pending_documents: 2, review_items: [{ code: "check", count: 1, message: "Нужна проверка" }], cashflow_ledger: { opening: "50.00", external_inflow: "100.00", external_outflow: "40.00", external_net: "60.00", internal_net: "30.00", internal_count: 1, unclassified_inflow: "100.00", unclassified_outflow: "100.00", unclassified_net: "0.00", unclassified_count: 2, opening_adjustment_net: "0.00", opening_adjustment_count: 0, closing: "140.00", activities: { operating: { inflow: "100.00", outflow: "0.00", net: "100.00" }, investing: { inflow: "0.00", outflow: "0.00", net: "0.00" }, financing: { inflow: "0.00", outflow: "40.00", net: "-40.00" } } }, cash_movements: [{ entry_id: 9, source: "bank; line", date: "2026-09-04", account: "51", title: "Банк", line_id: 10, currency: "USD", ledger_currency: "BYN", valuation_only: true, side: "debit" as const, amount: "100.00", dimensions: { note: "a\"b" }, cash_activity: "operating" }] };
afterEach(() => vi.unstubAllGlobals());

it("uses an explicit applied snapshot, entry API, and review", async () => {
  const fetchMock = vi.fn().mockImplementation((url: string) => {
    if (url === "/api/system/instance-organization") return Promise.resolve({ ok: true, json: async () => context });
    if (url.includes("/reports?")) return Promise.resolve({ ok: true, json: async () => report });
    if (url.endsWith("/entries/9")) return Promise.resolve({ ok: true, json: async () => ({ id: 9, source: "bank; line", operation: "bank_settlement", posting_date: "2026-09-04", explanation: "Синтетическая выписка", lines: [{ id: 10, account_code: "51", account_title: "Банк", side: "debit", amount: "100.00", currency: "BYN" }] }) });
    throw new Error(url);
  });
  vi.stubGlobal("fetch", fetchMock); render(<FinanceLedgerCashflow />); await screen.findByRole("button", { name: "Применить" });
  fireEvent.change(screen.getByLabelText("Начало периода ДДС"), { target: { value: "2026-09-01" } }); fireEvent.change(screen.getByLabelText("Конец периода ДДС"), { target: { value: "2026-09-30" } }); fireEvent.click(screen.getByRole("button", { name: "Применить" }));
  await screen.findAllByText("100.00 BYN"); expect(screen.getByText(/Неразобранные строки: 2/)).toBeInTheDocument(); expect(screen.getByText("Нужна проверка (1)")).toBeInTheDocument(); expect(screen.getByText(/Необработанные документы: 2/)).toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "Открыть" })); expect(await screen.findByText("Синтетическая выписка")).toBeInTheDocument(); expect(screen.getByText(/bank_settlement/)).toBeInTheDocument();
  expect(screen.getByText("100.00 BYN · валюта позиции: USD (переоценка; валюта строки: BYN)")).toBeInTheDocument();
  expect(screen.queryByText("100.00 USD")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/accounting/organizations/7/entries/9", { cache: "no-store" });
});

it("keeps the latest applied period and exports escaped snapshot", async () => {
  let old!: (value: unknown) => void; let latest!: (value: unknown) => void;
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    if (url === "/api/system/instance-organization") return Promise.resolve({ ok: true, json: async () => context });
    if (url.includes("end=2026-09-29")) return new Promise(resolve => { latest = resolve; });
    if (url.includes("/7/reports")) return new Promise(resolve => { old = resolve; });
    throw new Error(url);
  }));
  render(<FinanceLedgerCashflow />); await screen.findByRole("button", { name: "Применить" });
  fireEvent.change(screen.getByLabelText("Начало периода ДДС"), { target: { value: "2026-09-01" } });
  fireEvent.change(screen.getByLabelText("Конец периода ДДС"), { target: { value: "2026-09-30" } });
  fireEvent.click(screen.getByRole("button", { name: "Применить" }));
  fireEvent.change(screen.getByLabelText("Конец периода ДДС"), { target: { value: "2026-09-29" } });
  fireEvent.click(screen.getByRole("button", { name: "Применить" }));
  await act(async () => { latest({ ok: true, json: async () => ({ ...report, to: "2026-09-29", cashflow_ledger: { ...report.cashflow_ledger, closing: "200.00" } }) }); });
  await screen.findByText("200.00 BYN");
  await act(async () => { old({ ok: true, json: async () => report }); });
  await waitFor(() => expect(screen.queryByText("140.00 BYN")).not.toBeInTheDocument());
  const csv = cashflowCsv(report as never, { org: "7", start: "2026-09-01", end: "2026-09-30" }); expect(csv).toContain('"bank; line"'); expect(csv).toContain("Неклассифицированные строки;2"); expect(csv).toContain("Неклассифицированные выплаты;100.00"); expect(csv).toContain("Внутренний поток;30.00"); expect(csv).toContain("Валюта позиции или строки;Валюта строки при переоценке;Оценка");
});

it("shows member access errors", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => url === "/api/system/instance-organization" ? Promise.resolve({ ok: true, json: async () => context }) : Promise.resolve({ ok: false, json: async () => ({ detail: "Нет доступа" }) })));
  render(<FinanceLedgerCashflow />); await screen.findByRole("button", { name: "Применить" }); fireEvent.change(screen.getByLabelText("Начало периода ДДС"), { target: { value: "2026-09-01" } }); fireEvent.change(screen.getByLabelText("Конец периода ДДС"), { target: { value: "2026-09-30" } }); fireEvent.click(screen.getByRole("button", { name: "Применить" })); expect(await screen.findByRole("alert")).toHaveTextContent("Нет доступа");
});


it("rejects malformed report values without displaying a false balance", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve({ ok: true, json: async () => url === "/api/system/instance-organization"
    ? context
    : { ...report, cashflow_ledger: { ...report.cashflow_ledger, closing: "NaN" } } })));
  render(<FinanceLedgerCashflow />);
  await screen.findByRole("button", { name: "Применить" });

  fireEvent.change(screen.getByLabelText("Начало периода ДДС"), { target: { value: "2026-09-01" } });
  fireEvent.change(screen.getByLabelText("Конец периода ДДС"), { target: { value: "2026-09-30" } });
  fireEvent.click(screen.getByRole("button", { name: "Применить" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("неверный формат");
  expect(screen.queryByText("NaN BYN")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Скачать CSV" })).not.toBeInTheDocument();
});

it.each(["empty", "missing", "malformed", "populated-zero"] as const)("guards FinanceLedgerCashflow financial display and CSV for %s ledger data", async (state) => {
  const data: Record<string, unknown> = structuredClone(report);
  data.trial_balance = state === "empty" ? [] : state === "missing" ? undefined : state === "malformed" ? [null]
    : [{ account: "51", title: "Банк", off_balance: false, currency: "BYN", dimensions: {}, opening: "0.00", debit: "0.00", credit: "0.00", closing: "0.00" }];
  data.cashflow_ledger = Object.fromEntries(Object.entries(report.cashflow_ledger).map(([key, value]) => [key,
    key === "activities" ? Object.fromEntries(["operating", "investing", "financing"].map(activity => [activity, { inflow: "0.00", outflow: "0.00", net: "0.00" }]))
      : typeof value === "number" ? 0 : "0.00"]));
  data.cash_movements = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({ ok: true, json: async () => url.includes("instance-organization") ? context : data })));
  render(<FinanceLedgerCashflow />);
  await screen.findByRole("button", { name: "Применить" });
  fireEvent.change(screen.getByLabelText("Начало периода ДДС"), { target: { value: "2026-09-01" } });
  fireEvent.change(screen.getByLabelText("Конец периода ДДС"), { target: { value: "2026-09-30" } });
  fireEvent.click(screen.getByRole("button", { name: "Применить" }));
  const applied = { org: "7", start: "2026-09-01", end: "2026-09-30" };
  if (state === "populated-zero") {
    expect((await screen.findAllByText("0.00 BYN")).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Скачать CSV" })).toBeInTheDocument();
    expect(cashflowCsv(data as unknown as Parameters<typeof cashflowCsv>[0], applied)).toContain("0.00");
  } else {
    await screen.findByText(state === "empty" ? "Нет учётных данных ERP" : "Данные отчёта пока не подтверждены");
    expect(screen.queryByRole("button", { name: "Скачать CSV" })).not.toBeInTheDocument();
    expect(screen.queryAllByText("0.00 BYN")).toHaveLength(0);
    expect(screen.queryByText(/Расхождений баланса нет/)).not.toBeInTheDocument();
    expect(() => cashflowCsv(data as unknown as Parameters<typeof cashflowCsv>[0], applied)).toThrow(/Нет подтверждённых строк/);
  }
});
