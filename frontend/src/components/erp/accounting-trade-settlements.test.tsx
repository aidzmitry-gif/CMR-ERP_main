import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { AccountingTradeSettlements } from "./accounting-trade-settlements";

const result = (org = 1) => ({
  organization_id: org, from: "2026-09-01", to: "2026-09-30", status: "preliminary",
  scope: "posted_accounts_60_62", due_dates_verified: false, statutory_certified: false,
  review_items: [{ code: "incomplete_analytics", count: 0 }, { code: "unclassified_balance", count: 0 },
    { code: "mixed_currency_document", count: 0 }],
  totals_byn: { receivable: "60.00", payable: "0.00", customer_advance: "40.00",
    supplier_advance: "0.00", unclassified: "0.00" },
  rows: [{ key: "customer-doc", account: "62", account_title: "Покупатели",
    counterparty: "Покупатель", contract: "Договор 1", document: "sales:document:42",
    classification: "receivable", balance_kind: "receivable", analytics_complete: true, currencies: ["BYN"],
    opening_byn: "0.00", debit_byn: "120.00", credit_byn: "60.00", closing_byn: "60.00",
    bank_receipts_byn: "0.00", bank_payments_byn: "0.00", offset_debit_byn: "0.00", offset_credit_byn: "60.00",
    movements: [{ entry_id: 7, line_id: 11, date: "2026-09-03", source: "source:7",
      operation: "settlement_offset", side: "credit", amount_byn: "60.00", period_bucket: "movement", kind: "advance_offset" }],
  }, { key: "advance", account: "60", account_title: "Авансы", counterparty: "Покупатель",
    contract: "Договор 1", document: "customer-advance:buyer-1", classification: "customer_advance",
    balance_kind: "customer_advance", analytics_complete: true, currencies: ["BYN"], opening_byn: "0.00",
    debit_byn: "60.00", credit_byn: "100.00", closing_byn: "-40.00",
    bank_receipts_byn: "100.00", bank_payments_byn: "0.00", offset_debit_byn: "60.00", offset_credit_byn: "0.00",
    movements: [],
  }],
});

afterEach(() => vi.unstubAllGlobals());

it("shows real document balances, advances and linked ledger entries", async () => {
  const onEntry = vi.fn();
  const fetcher = vi.fn(async () => ({ ok: true, json: async () => result() }));
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingTradeSettlements org="1" start="2026-09-01" end="2026-09-30" onEntry={onEntry} />);
  expect(await screen.findByText("Покупатель · sales:document:42")).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledWith(expect.stringContaining("/organizations/1/reports/trade-settlements?start=2026-09-01&end=2026-09-30"), expect.objectContaining({ cache: "no-store" }));
  expect(screen.getByText(/сроки оплаты и просрочка пока не подтверждены/i)).toBeInTheDocument();
  fireEvent.click(screen.getByText("Покупатель · sales:document:42"));
  const reportRow = screen.getByText("Покупатель · sales:document:42").closest("details")!;
  expect(within(reportRow).getByText("Зачёт аванса", { exact: false })).toBeInTheDocument();
  fireEvent.click(within(reportRow).getByRole("button", { name: "№ 7" }));
  expect(onEntry).toHaveBeenCalledWith(7);
  fireEvent.change(screen.getByRole("combobox", { name: "Вид расчётов" }), { target: { value: "advances" } });
  expect(screen.getByText("Покупатель · customer-advance:buyer-1")).toBeInTheDocument();
  expect(screen.queryByText("Покупатель · sales:document:42")).not.toBeInTheDocument();
});

it("clears old book data and rejects a response for the wrong organization", async () => {
  let resolveOld!: (value: unknown) => void;
  const fetcher = vi.fn((url: string) => url.includes("/organizations/1/")
    ? new Promise((resolve) => { resolveOld = resolve; })
    : Promise.resolve({ ok: true, json: async () => result(1) }));
  vi.stubGlobal("fetch", fetcher);
  const view = render(<AccountingTradeSettlements org="1" start="2026-09-01" end="2026-09-30" onEntry={vi.fn()} />);
  await waitFor(() => expect(resolveOld).toBeDefined());
  view.rerender(<AccountingTradeSettlements org="2" start="2026-09-01" end="2026-09-30" onEntry={vi.fn()} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("не соответствует выбранной книге");
  resolveOld({ ok: true, json: async () => result(1) });
  expect(screen.queryByText("Покупатель · sales:document:42")).not.toBeInTheDocument();
});

it("hides a loaded report immediately when the selected book changes", async () => {
  let resolveNew!: (value: unknown) => void;
  vi.stubGlobal("fetch", vi.fn((url: string) => url.includes("/organizations/1/")
    ? Promise.resolve({ ok: true, json: async () => result(1) })
    : new Promise((resolve) => { resolveNew = resolve; })));
  const view = render(<AccountingTradeSettlements org="1" start="2026-09-01" end="2026-09-30" onEntry={vi.fn()} />);
  await screen.findByText("Покупатель · sales:document:42");
  view.rerender(<AccountingTradeSettlements org="2" start="2026-09-01" end="2026-09-30" onEntry={vi.fn()} />);
  expect(screen.queryByText("Покупатель · sales:document:42")).not.toBeInTheDocument();
  expect(screen.getByText("Загрузка расчётов…")).toBeInTheDocument();
  await waitFor(() => expect(resolveNew).toBeDefined());
  resolveNew({ ok: true, json: async () => result(2) });
  expect(await screen.findByText("Покупатель · sales:document:42")).toBeInTheDocument();
});
