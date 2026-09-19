import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { FinanceLedgerPnl, pnlCsv } from "./finance-ledger-pnl";

const report = { organization_id: 7, from: "2026-09-01", to: "2026-09-30", status: "preliminary", pending_documents: 2,
  review_items: [{ code: "check", count: 1, message: "Нужна проверка" }], pnl: { income: "20.00", expenses: "3.33", profit: "16.67" },
  pnl_movements: [{ entry_id: 11, source: "sale; one", date: "2026-09-04", account: "90.1", title: "Доход", line_id: 21, currency: "USD", side: "credit" as const, amount: "20.00", dimensions: { note: "a\"b\nc" }, category: "income" as const }, { entry_id: 11, source: "sale", date: "2026-09-04", account: "90.4", title: "Расход", line_id: 22, currency: "BYN", side: "debit" as const, amount: "3.33", dimensions: {}, category: "expense" as const }] };

afterEach(() => vi.unstubAllGlobals());

it("requires explicit organization and displays only the applied accounting report", async () => {
  const fetchMock = vi.fn().mockImplementation((url: string) => {
    if (url === "/api/accounting/organizations") return Promise.resolve({ ok: true, json: async () => [{ id: 7, name: "Компания A", unp: "111" }] });
    if (url.includes("/reports?")) return Promise.resolve({ ok: true, json: async () => report });
    if (url.endsWith("/entries/11")) return Promise.resolve({ ok: true, json: async () => ({ id: 11, source: "sale; one", operation: "sale", explanation: "Синтетическая операция", posting_date: "2026-09-04", lines: [] }) });
    throw new Error(url);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<FinanceLedgerPnl />);
  await screen.findByRole("option", { name: "Компания A · 111" });
  fireEvent.click(screen.getByRole("button", { name: "Применить" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Выберите организацию");
  expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/reports?"))).toBe(false);
  fireEvent.change(screen.getByLabelText("Организация P&L"), { target: { value: "7" } });
  fireEvent.change(screen.getByLabelText("Начало периода P&L"), { target: { value: "2026-09-01" } });
  fireEvent.change(screen.getByLabelText("Конец периода P&L"), { target: { value: "2026-09-30" } });
  fireEvent.click(screen.getByRole("button", { name: "Применить" }));
  await screen.findByText("16.67 BYN");
  expect(screen.getByText("sale; one · №11")).toBeInTheDocument();
  fireEvent.click(screen.getAllByRole("button", { name: "Открыть" })[0]);
  expect(await screen.findByText("Синтетическая операция")).toBeInTheDocument();
  expect(screen.getByText("20.00 BYN (валюта операции: USD)")).toBeInTheDocument();
  expect(screen.queryByText("20.00 USD")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/accounting/organizations/7/entries/11", { cache: "no-store" });
});

it("keeps the latest organization and date response when requests resolve out of order", async () => {
  let first!: (value: unknown) => void;
  let second!: (value: unknown) => void;
  const fetchMock = vi.fn().mockImplementation((url: string) => {
    if (url === "/api/accounting/organizations") return Promise.resolve({ ok: true, json: async () => [{ id: 7, name: "A", unp: "1" }, { id: 8, name: "B", unp: "2" }] });
    if (url.includes("/7/reports")) return new Promise((resolve) => { first = resolve; });
    if (url.includes("/8/reports")) return new Promise((resolve) => { second = resolve; });
    throw new Error(url);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<FinanceLedgerPnl />);
  await screen.findByRole("option", { name: "A · 1" });
  fireEvent.change(screen.getByLabelText("Организация P&L"), { target: { value: "7" } }); fireEvent.change(screen.getByLabelText("Начало периода P&L"), { target: { value: "2026-09-01" } }); fireEvent.change(screen.getByLabelText("Конец периода P&L"), { target: { value: "2026-09-30" } }); fireEvent.click(screen.getByRole("button", { name: "Применить" }));
  fireEvent.change(screen.getByLabelText("Организация P&L"), { target: { value: "8" } }); fireEvent.click(screen.getByRole("button", { name: "Применить" }));
  second({ ok: true, json: async () => ({ ...report, organization_id: 8, pnl: { ...report.pnl, profit: "18.00" } }) });
  await screen.findByText("18.00 BYN");
  first({ ok: true, json: async () => report });
  await waitFor(() => expect(screen.queryByText("16.67 BYN")).not.toBeInTheDocument());
  expect(screen.getByText(/организация 8/)).toBeInTheDocument();
});

it("reports member access failures and exports exactly the displayed response", async () => {
  const csv = pnlCsv(report, { org: "7", start: "2026-09-01", end: "2026-09-30" });
  expect(csv).toMatch(/^Организация;С;По;Статус;Доходы;Расходы;Финансовый результат;/);
  expect(csv).toContain("20.00;3.33;16.67");
  expect(csv).toContain('"sale; one"');
  expect(csv).toContain('"{""note"":""a\\""b\\nc""}"');
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => url === "/api/accounting/organizations"
    ? Promise.resolve({ ok: true, json: async () => [{ id: 7, name: "A", unp: "1" }] })
    : Promise.resolve({ ok: false, json: async () => ({ detail: "Нет доступа к книге" }) })));
  render(<FinanceLedgerPnl />);
  await screen.findByRole("option", { name: "A · 1" });
  fireEvent.change(screen.getByLabelText("Организация P&L"), { target: { value: "7" } }); fireEvent.change(screen.getByLabelText("Начало периода P&L"), { target: { value: "2026-09-01" } }); fireEvent.change(screen.getByLabelText("Конец периода P&L"), { target: { value: "2026-09-30" } }); fireEvent.click(screen.getByRole("button", { name: "Применить" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Нет доступа к книге");
});
