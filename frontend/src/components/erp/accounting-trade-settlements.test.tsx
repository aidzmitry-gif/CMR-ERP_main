import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { AccountingTradeSettlements, buildTradeSettlementsCsv } from "./accounting-trade-settlements";

const result = (org = 1): Parameters<typeof buildTradeSettlementsCsv>[0] => ({
  organization_id: org, from: "2026-09-01", to: "2026-09-30", status: "preliminary",
  scope: "posted_accounts_60_62", due_dates_verified: false, statutory_certified: false,
  review_items: [{ code: "incomplete_analytics", count: 0 }, { code: "unclassified_balance", count: 0 },
    { code: "mixed_currency_document", count: 0 }, { code: "osv_document_mismatch", count: 0 }],
  osv_reconciliation: { status: "matched" as "matched" | "mismatch", basis: "same_posted_journal", osv_line_count: 2,
    document_line_count: 2, missing_osv_lines: 0, extra_document_lines: 0,
    missing_postings: [] as { entry_id: number; line_id: number }[],
    accounts: [] as { account: string; matched: boolean; osv_byn: Record<string, string>;
      documents_byn: Record<string, string> }[] },
  totals_byn: { receivable: "60.00", payable: "0.00", customer_advance: "40.00",
    supplier_advance: "0.00", unclassified: "0.00" },
  rows: [{ key: "customer-doc", account: "62", account_title: "Покупатели", category: "asset",
    counterparty: "Покупатель", contract: "Договор 1", document: "sales:document:42",
    classification: "receivable", balance_kind: "receivable", analytics_complete: true, currencies: ["BYN"],
    opening_byn: "0.00", debit_byn: "120.00", credit_byn: "60.00", closing_byn: "60.00",
    bank_receipts_byn: "0.00", bank_payments_byn: "0.00", offset_debit_byn: "0.00", offset_credit_byn: "60.00",
    movements: [{ entry_id: 7, line_id: 11, date: "2026-09-03", source: "source:7", source_version: 1,
      operation: "settlement_offset", side: "credit", amount_byn: "60.00", period_bucket: "movement", kind: "advance_offset" }],
  }, { key: "advance", account: "60", account_title: "Авансы", category: "liability", counterparty: "Покупатель",
    contract: "Договор 1", document: "customer-advance:buyer-1", classification: "customer_advance",
    balance_kind: "customer_advance", analytics_complete: true, currencies: ["BYN"], opening_byn: "0.00",
    debit_byn: "60.00", credit_byn: "100.00", closing_byn: "-40.00",
    bank_receipts_byn: "100.00", bank_payments_byn: "0.00", offset_debit_byn: "60.00", offset_credit_byn: "0.00",
    movements: [{ entry_id: 8, line_id: 12, date: "2026-09-03", source: "source:8", source_version: 1,
      operation: "bank_settlement", side: "credit", amount_byn: "100.00", period_bucket: "movement",
      kind: "bank_receipt" }],
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
  expect(screen.getByText(/Внутренняя сверка с ОСВ: суммы в BYN и строки 60\/62 совпали \(количество: 2\)/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Скачать CSV для внутренней сверки" })).toBeInTheDocument();
  fireEvent.click(screen.getByText("Покупатель · sales:document:42"));
  const reportRow = screen.getByText("Покупатель · sales:document:42").closest("details")!;
  expect(within(reportRow).getByText("Зачёт аванса", { exact: false })).toBeInTheDocument();
  fireEvent.click(within(reportRow).getByRole("button", { name: "№ 7" }));
  expect(onEntry).toHaveBeenCalledWith(7);
  fireEvent.change(screen.getByRole("combobox", { name: "Вид расчётов" }), { target: { value: "advances" } });
  expect(screen.getByText("Покупатель · customer-advance:buyer-1")).toBeInTheDocument();
  expect(screen.queryByText("Покупатель · sales:document:42")).not.toBeInTheDocument();
});

it("warns on an OSV mismatch and links the missing posting", async () => {
  const onEntry = vi.fn();
  const data = result();
  data.osv_reconciliation.status = "mismatch";
  data.osv_reconciliation.osv_line_count = 3;
  data.osv_reconciliation.missing_osv_lines = 1;
  data.osv_reconciliation.missing_postings = [{ entry_id: 9, line_id: 19 }];
  data.osv_reconciliation.accounts = [{ account: "62.9", matched: false,
    osv_byn: { opening: "0.00", debit: "30.00", credit: "0.00", closing: "30.00" },
    documents_byn: { opening: "0.00", debit: "0.00", credit: "0.00", closing: "0.00" } }];
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => data })));
  render(<AccountingTradeSettlements org="1" start="2026-09-01" end="2026-09-30" onEntry={onEntry} />);
  const warning = await screen.findByRole("alert");
  expect(warning).toHaveTextContent("документная сводка неполна");
  expect(warning).toHaveTextContent("Счёт 62.9, ОСВ / документы (BYN): начало 0.00 / 0.00; Дт 30.00 / 0.00");
  expect(screen.queryByText("Авансы покупателей")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Скачать CSV для внутренней сверки" })).not.toBeInTheDocument();
  fireEvent.click(within(warning).getByRole("button", { name: "Проводка № 9, строка 19" }));
  expect(onEntry).toHaveBeenCalledWith(9);
});

it("exports exact scoped ledger references without spreadsheet formulas", () => {
  const data = result();
  data.rows[0].counterparty = "=HYPERLINK(\"https://example.invalid\",\"Buyer\")";
  data.rows[0].movements.push({ entry_id: 9, line_id: 13, date: "2026-09-04",
    source: "source:9", source_version: 2, operation: "bank_settlement", side: "credit",
    amount_byn: "10.00", period_bucket: "movement", kind: "bank_receipt" });
  data.osv_reconciliation.osv_line_count = 3;
  data.osv_reconciliation.document_line_count = 3;
  const csv = buildTradeSettlementsCsv(data);
  expect(csv.charCodeAt(0)).toBe(0xFEFF);
  const lines = csv.split("\r\n");
  expect(lines).toHaveLength(4);
  expect(lines[0]).toContain("movement_count,entry_line_ids,source_references_json");
  expect(lines[1]).toContain("\"'=HYPERLINK(\"\"https://example.invalid\"\",\"\"Buyer\"\")\"");
  expect(lines[1]).toContain(',2,"7:11|9:13",');
  expect(lines[1]).toContain("source:7");
  expect(lines[1]).toContain("source:9");
  expect(lines[2]).toContain(',1,"8:12",');
  expect(lines[2]).toContain("source:8");
  expect(csv).toContain("\"2026-09-01\",\"2026-09-30\",\"preliminary_internal\"");
  data.osv_reconciliation.status = "mismatch";
  expect(() => buildTradeSettlementsCsv(data)).toThrow("не совпадает с ОСВ");
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
  view.rerender(<AccountingTradeSettlements org="2" start="2026-09-05" end="2026-09-30" onEntry={vi.fn()} />);
  expect(screen.queryByRole("button", { name: "Скачать CSV для внутренней сверки" })).not.toBeInTheDocument();
});
