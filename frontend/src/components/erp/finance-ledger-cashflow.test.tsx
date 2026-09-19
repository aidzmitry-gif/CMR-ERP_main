import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { FinanceLedgerCashflow, cashflowCsv } from "./finance-ledger-cashflow";

const report = { organization_id: 7, from: "2026-09-01", to: "2026-09-30", status: "preliminary", pending_documents: 2, review_items: [{ code: "check", count: 1, message: "Нужна проверка" }], cashflow_ledger: { opening: "50.00", external_inflow: "100.00", external_outflow: "40.00", external_net: "60.00", internal_net: "30.00", internal_count: 1, unclassified_inflow: "100.00", unclassified_outflow: "100.00", unclassified_net: "0.00", unclassified_count: 2, opening_adjustment_net: "0.00", opening_adjustment_count: 0, closing: "140.00", activities: { operating: { inflow: "100.00", outflow: "0.00", net: "100.00" }, investing: { inflow: "0.00", outflow: "0.00", net: "0.00" }, financing: { inflow: "0.00", outflow: "40.00", net: "-40.00" } } }, cash_movements: [{ entry_id: 9, source: "bank; line", date: "2026-09-04", account: "51", title: "Банк", line_id: 10, currency: "USD", side: "debit" as const, amount: "100.00", dimensions: { note: "a\"b" }, cash_activity: "operating" }] };
afterEach(() => vi.unstubAllGlobals());

it("uses an explicit applied snapshot, entry API, and review", async () => {
  const fetchMock = vi.fn().mockImplementation((url: string) => {
    if (url === "/api/accounting/organizations") return Promise.resolve({ ok: true, json: async () => [{ id: 7, name: "A", unp: "1" }] });
    if (url.includes("/reports?")) return Promise.resolve({ ok: true, json: async () => report });
    if (url.endsWith("/entries/9")) return Promise.resolve({ ok: true, json: async () => ({ id: 9, source: "bank; line", operation: "bank_settlement", posting_date: "2026-09-04", explanation: "Синтетическая выписка", lines: [{ id: 10, account_code: "51", account_title: "Банк", side: "debit", amount: "100.00", currency: "BYN" }] }) });
    throw new Error(url);
  });
  vi.stubGlobal("fetch", fetchMock); render(<FinanceLedgerCashflow />); await screen.findByRole("option", { name: "A · 1" });
  fireEvent.click(screen.getByRole("button", { name: "Применить" })); expect(await screen.findByRole("alert")).toHaveTextContent("Выберите организацию");
  fireEvent.change(screen.getByLabelText("Организация ДДС"), { target: { value: "7" } }); fireEvent.change(screen.getByLabelText("Начало периода ДДС"), { target: { value: "2026-09-01" } }); fireEvent.change(screen.getByLabelText("Конец периода ДДС"), { target: { value: "2026-09-30" } }); fireEvent.click(screen.getByRole("button", { name: "Применить" }));
  await screen.findAllByText("100.00 BYN"); expect(screen.getByText(/Неразобранные строки: 2/)).toBeInTheDocument(); expect(screen.getByText("Нужна проверка (1)")).toBeInTheDocument(); expect(screen.getByText(/Необработанные документы: 2/)).toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "Открыть" })); expect(await screen.findByText("Синтетическая выписка")).toBeInTheDocument(); expect(screen.getByText(/bank_settlement/)).toBeInTheDocument();
  expect(screen.getByText("100.00 BYN (валюта операции: USD)")).toBeInTheDocument();
  expect(screen.queryByText("100.00 USD")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/accounting/organizations/7/entries/9", { cache: "no-store" });
});

it("keeps the latest response and exports escaped snapshot", async () => {
  let old!: (value: unknown) => void; let latest!: (value: unknown) => void;
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
    if (url === "/api/accounting/organizations") return Promise.resolve({ ok: true, json: async () => [{ id: 7, name: "A", unp: "1" }, { id: 8, name: "B", unp: "2" }] });
    if (url.includes("/7/reports")) return new Promise(resolve => { old = resolve; });
    if (url.includes("/8/reports")) return new Promise(resolve => { latest = resolve; });
    throw new Error(url);
  }));
  render(<FinanceLedgerCashflow />); await screen.findByRole("option", { name: "A · 1" });
  fireEvent.change(screen.getByLabelText("Организация ДДС"), { target: { value: "7" } }); fireEvent.change(screen.getByLabelText("Начало периода ДДС"), { target: { value: "2026-09-01" } }); fireEvent.change(screen.getByLabelText("Конец периода ДДС"), { target: { value: "2026-09-30" } }); fireEvent.click(screen.getByRole("button", { name: "Применить" })); fireEvent.change(screen.getByLabelText("Организация ДДС"), { target: { value: "8" } }); fireEvent.click(screen.getByRole("button", { name: "Применить" }));
  latest({ ok: true, json: async () => ({ ...report, organization_id: 8, cashflow_ledger: { ...report.cashflow_ledger, closing: "200.00" } }) }); await screen.findByText("200.00 BYN"); old({ ok: true, json: async () => report }); await waitFor(() => expect(screen.queryByText("140.00 BYN")).not.toBeInTheDocument());
  const csv = cashflowCsv(report as never, { org: "7", start: "2026-09-01", end: "2026-09-30" }); expect(csv).toContain('"bank; line"'); expect(csv).toContain("Неклассифицированные строки;2"); expect(csv).toContain("Неклассифицированные выплаты;100.00"); expect(csv).toContain("Внутренний поток;30.00");
});

it("shows member access errors", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => url === "/api/accounting/organizations" ? Promise.resolve({ ok: true, json: async () => [{ id: 7, name: "A", unp: "1" }] }) : Promise.resolve({ ok: false, json: async () => ({ detail: "Нет доступа" }) })));
  render(<FinanceLedgerCashflow />); await screen.findByRole("option", { name: "A · 1" }); fireEvent.change(screen.getByLabelText("Организация ДДС"), { target: { value: "7" } }); fireEvent.change(screen.getByLabelText("Начало периода ДДС"), { target: { value: "2026-09-01" } }); fireEvent.change(screen.getByLabelText("Конец периода ДДС"), { target: { value: "2026-09-30" } }); fireEvent.click(screen.getByRole("button", { name: "Применить" })); expect(await screen.findByRole("alert")).toHaveTextContent("Нет доступа");
});


it("rejects malformed report values without displaying a false balance", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve({ ok: true, json: async () => url === "/api/accounting/organizations"
    ? [{ id: 7, name: "A", unp: "1" }]
    : { ...report, cashflow_ledger: { ...report.cashflow_ledger, closing: "NaN" } } })));
  render(<FinanceLedgerCashflow />);
  await screen.findByRole("option", { name: "A · 1" });
  fireEvent.change(screen.getByLabelText("Организация ДДС"), { target: { value: "7" } });
  fireEvent.change(screen.getByLabelText("Начало периода ДДС"), { target: { value: "2026-09-01" } });
  fireEvent.change(screen.getByLabelText("Конец периода ДДС"), { target: { value: "2026-09-30" } });
  fireEvent.click(screen.getByRole("button", { name: "Применить" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("неверный формат");
  expect(screen.queryByText("NaN BYN")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Скачать CSV" })).not.toBeInTheDocument();
});
