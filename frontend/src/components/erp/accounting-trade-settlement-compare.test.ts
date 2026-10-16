import { expect, it } from "vitest";

import { compareTradeDocumentCsv, EXTERNAL_TRADE_HEADER, type ErpTradePosition } from "./accounting-trade-settlement-compare";

const position = (change: Partial<ErpTradePosition> = {}): ErpTradePosition => ({
  account: "62", category: "asset", counterparty: "Клиент, ООО", contract: "Договор 1",
  document: 'Счёт "А"', analytics_complete: true,
  opening_byn: "100.00", debit_byn: "0.00", credit_byn: "40.00", closing_byn: "60.00",
  movements: [{ entry_id: 7, line_id: 11 }, { entry_id: 8, line_id: 12 }], ...change,
});
const scope = (rows: ErpTradePosition[] = [position()]) => ({
  organization_id: 3, from: "2026-09-01", to: "2026-09-30", rows,
});
const cell = (value: string) => `"${value.replaceAll('"', '""')}"`;
const external = (rows: string[][]) => `\uFEFF${EXTERNAL_TRADE_HEADER.join(",")}\r\n${rows.map((row) => row.map(cell).join(",")).join("\r\n")}\r\n`;
const row = (change: Partial<Record<(typeof EXTERNAL_TRADE_HEADER)[number], string>> = {}) => {
  const data = { source_system: "1C", organization_id: "3", period_start: "2026-09-01", period_end: "2026-09-30",
    account: "62", category: "asset", counterparty: "Клиент, ООО", contract: "Договор 1",
    settlement_document: 'Счёт "А"', opening_byn: "100.00", debit_byn: "0.00",
    credit_byn: "40.00", closing_byn: "60.00", ...change };
  return EXTERNAL_TRADE_HEADER.map((name) => data[name]);
};

it("compares exact document identity and partial payment in cents", () => {
  const result = compareTradeDocumentCsv(external([row()]), scope());
  expect(result).toEqual({ status: "matched", external_rows: 1, erp_rows: 1, matched_rows: 1, issues: [] });
});

it("shows amount differences and both directions of missing document", () => {
  const results = compareTradeDocumentCsv(external([
    row({ credit_byn: "50.00", closing_byn: "50.00" }),
    row({ settlement_document: "Только 1С" }),
  ]), scope([position(), position({ document: "Только ERP" })]));
  expect(results.status).toBe("differences");
  expect(results.matched_rows).toBe(0);
  expect(results.issues.map((issue) => issue.kind)).toEqual(["amount_difference", "missing_in_1c", "only_in_1c"]);
  expect(results.issues[0].differing_fields).toEqual(["credit_byn", "closing_byn"]);
  expect(results.issues[0].erp?.movements).toEqual([{ entry_id: 7, line_id: 11 }, { entry_id: 8, line_id: 12 }]);
});

it("rejects a foreign book, duplicate identity, incomplete ERP analytics and invalid balance", () => {
  expect(() => compareTradeDocumentCsv(external([row({ organization_id: "4" })]), scope())).toThrow("юрлицу");
  expect(() => compareTradeDocumentCsv(external([row(), row()]), scope())).toThrow("повторяющийся документ");
  expect(() => compareTradeDocumentCsv(external([row()]), scope([position({ contract: null })]))).toThrow("полной аналитики");
  expect(() => compareTradeDocumentCsv(external([row({ closing_byn: "61.00" })]), scope())).toThrow("конечным сальдо");
  expect(() => compareTradeDocumentCsv(external([row({ debit_byn: "-1.00", closing_byn: "59.00" })]), scope())).toThrow("отрицательный оборот");
});

it("rejects malformed or empty CSV rather than silently treating it as no 1C debt", () => {
  expect(() => compareTradeDocumentCsv(EXTERNAL_TRADE_HEADER.join(",") + "\r\n", scope())).toThrow("не содержит документов");
  expect(() => compareTradeDocumentCsv(external([row()]).replace('"Клиент, ООО"', '"Клиент, ООО'), scope())).toThrow("кавыч");
  expect(() => compareTradeDocumentCsv(external([row()]).replace("source_system", "source_system_changed"), scope())).toThrow("заголовком");
});
