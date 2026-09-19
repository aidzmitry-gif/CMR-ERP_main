import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { balanceCsv, FinanceLedgerBalance } from "./finance-ledger-balance";

const report = {
  organization_id: 7, from: "2026-09-01", to: "2026-09-30", status: "preliminary", pending_documents: 2,
  review_items: [{ code: "check", count: 1, message: "Нужна проверка" }],
  balance: { assets: "31.67", liabilities: "14.00", equity: "0.00", current_result: "16.67", difference: "1.00" },
  balance_movements: [
    { entry_id: 9, source: "opening; line", date: "2026-09-01", account: "51", title: "Банк", line_id: 10, currency: "BYN", ledger_currency: "USD", valuation_only: true, side: "debit" as const, amount: "15.00", dimensions: { account: "main" }, category: "asset" as const, period_bucket: "opening" as const },
    { entry_id: 11, source: "sale", date: "2026-09-04", account: "90.1", title: "Доход", line_id: 21, currency: "BYN", side: "credit" as const, amount: "20.00", dimensions: { note: "a\"b\nc" }, category: "income" as const, period_bucket: "movement" as const },
  ],
};

afterEach(() => vi.unstubAllGlobals());

it("requires an applied organization, exposes the exact balance equation, and drills into a source entry", async () => {
  const fetchMock = vi.fn().mockImplementation((url: string) => {
    if (url === "/api/accounting/organizations") return Promise.resolve({ ok: true, json: async () => [{ id: 7, name: "Компания A", unp: "111" }] });
    if (url.includes("/reports?")) return Promise.resolve({ ok: true, json: async () => report });
    if (url.endsWith("/entries/9")) return Promise.resolve({ ok: true, json: async () => ({ id: 9, source: "opening; line", operation: "opening_import", posting_date: "2026-09-01", explanation: "Синтетический ввод остатков", lines: [{ id: 10, account_code: "51", account_title: "Банк", side: "debit", amount: "15.00", currency: "USD" }] }) });
    throw new Error(url);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<FinanceLedgerBalance />);
  await screen.findByRole("option", { name: "Компания A · 111" });
  fireEvent.click(screen.getByRole("button", { name: "Применить" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Выберите организацию");
  expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/reports?"))).toBe(false);

  fireEvent.change(screen.getByLabelText("Организация баланса"), { target: { value: "7" } });
  fireEvent.change(screen.getByLabelText("Начало периода баланса"), { target: { value: "2026-09-01" } });
  fireEvent.change(screen.getByLabelText("Конец периода баланса"), { target: { value: "2026-09-30" } });
  fireEvent.click(screen.getByRole("button", { name: "Применить" }));

  await screen.findByText("31.67 BYN");
  expect(screen.getByText("Нужна проверка (1)")).toBeInTheDocument();
  expect(screen.getByText(/Необработанные документы:/)).toHaveTextContent("Необработанные документы: 2");
  expect(screen.getByText("Уравнение: 31.67 = 14.00 + 0.00 + 16.67 + 1.00 BYN")).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("Расхождение баланса: 1.00 BYN. Требуется проверка.");
  expect(screen.getByText(/Остаток на начало/)).toBeInTheDocument();
  expect(screen.getByText(/15.00 BYN \(переоценка; книга: USD\)/)).toBeInTheDocument();
  fireEvent.click(screen.getAllByRole("button", { name: "Открыть" })[0]);
  expect(await screen.findByText("Синтетический ввод остатков")).toBeInTheDocument();
  expect(screen.getByText(/15.00 BYN · валюта строки: USD/)).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/accounting/organizations/7/entries/9", { cache: "no-store" });
});

it("exports the displayed response and rejects malformed balance totals", async () => {
  const csv = balanceCsv(report, { org: "7", start: "2026-09-01", end: "2026-09-30" });
  expect(csv).toContain("Активы;31.67");
  expect(csv).toContain('"opening; line"');
  expect(csv).toContain('a\\""b');
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve({ ok: true, json: async () => url === "/api/accounting/organizations"
    ? [{ id: 7, name: "A", unp: "1" }]
    : { ...report, balance: { ...report.balance, assets: "NaN" } } })));
  render(<FinanceLedgerBalance />);
  await screen.findByRole("option", { name: "A · 1" });
  fireEvent.change(screen.getByLabelText("Организация баланса"), { target: { value: "7" } });
  fireEvent.change(screen.getByLabelText("Начало периода баланса"), { target: { value: "2026-09-01" } });
  fireEvent.change(screen.getByLabelText("Конец периода баланса"), { target: { value: "2026-09-30" } });
  fireEvent.click(screen.getByRole("button", { name: "Применить" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("неверный формат");
  await waitFor(() => expect(screen.queryByText("NaN BYN")).not.toBeInTheDocument());
});
