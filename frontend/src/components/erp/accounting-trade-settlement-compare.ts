/** Browser-only comparison workpaper. The caller keeps the source bytes and digest local. */

export const EXTERNAL_TRADE_HEADER = ["source_system", "organization_id", "period_start", "period_end",
  "account", "category", "counterparty", "contract", "settlement_document",
  "opening_byn", "debit_byn", "credit_byn", "closing_byn"] as const;

type AmountField = "opening_byn" | "debit_byn" | "credit_byn" | "closing_byn";
const amountFields: AmountField[] = ["opening_byn", "debit_byn", "credit_byn", "closing_byn"];
type Identity = { account: string; category: string; counterparty: string; contract: string; document: string };
type Amounts = Record<AmountField, string>;
type Position = Identity & Amounts;
export type ErpTradePosition = Omit<Position, "counterparty" | "contract" | "document"> & {
  counterparty: string | null; contract: string | null; document: string | null;
  analytics_complete: boolean; movements: { entry_id: number; line_id: number }[];
};
export type TradeComparisonIssue = {
  kind: "missing_in_1c" | "only_in_1c" | "amount_difference";
  identity: Identity;
  erp: ErpTradePosition | null;
  external: Position | null;
  differing_fields: AmountField[];
};
export type TradeComparison = {
  status: "matched" | "differences";
  external_rows: number; erp_rows: number; matched_rows: number;
  issues: TradeComparisonIssue[];
};

function csvRows(input: string): string[][] {
  const text = input.startsWith("\uFEFF") ? input.slice(1) : input;
  if (!text || text.includes("\u0000") || text.includes("\uFFFD")) throw new Error("CSV 1С пуст или имеет некорректную кодировку UTF-8.");
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  let afterQuote = false;
  const finishCell = () => { row.push(cell); cell = ""; afterQuote = false; };
  const finishRow = () => {
    finishCell();
    if (row.length === 1 && row[0] === "") throw new Error("CSV 1С содержит пустую строку.");
    rows.push(row); row = [];
    if (rows.length > 5001) throw new Error("CSV 1С содержит более 5000 документов.");
  };
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (quoted) {
      if (char === '"' && text[i + 1] === '"') { cell += '"'; i += 1; }
      else if (char === '"') { quoted = false; afterQuote = true; }
      else cell += char;
    } else if (char === ",") finishCell();
    else if (char === "\n" || char === "\r") {
      if (char === "\r") {
        if (text[i + 1] !== "\n") throw new Error("CSV 1С содержит некорректный конец строки.");
        i += 1;
      }
      finishRow();
    } else if (char === '"' && !cell && !afterQuote) quoted = true;
    else if (char === '"' || afterQuote) throw new Error("CSV 1С содержит некорректные кавычки.");
    else cell += char;
  }
  if (quoted) throw new Error("CSV 1С содержит незакрытую кавычку.");
  if (row.length || cell || afterQuote) finishRow();
  return rows;
}

function cents(value: string): bigint {
  if (!/^-?(?:0|[1-9]\d*)\.\d{2}$/.test(value)) throw new Error("Некорректная сумма BYN в CSV.");
  const negative = value.startsWith("-");
  const [units, fraction] = (negative ? value.slice(1) : value).split(".");
  const result = BigInt(units) * 100n + BigInt(fraction);
  return negative ? -result : result;
}

function validAmounts(row: Amounts) {
  const opening = cents(row.opening_byn);
  const debit = cents(row.debit_byn);
  const credit = cents(row.credit_byn);
  const closing = cents(row.closing_byn);
  if (debit < 0n || credit < 0n || opening + debit - credit !== closing) {
    throw new Error("CSV содержит отрицательный оборот или строку с неверным конечным сальдо.");
  }
}

function identity(row: Identity): string {
  for (const value of [row.account, row.category, row.counterparty, row.contract, row.document]) {
    if (!value || value !== value.trim()) throw new Error("В расчётах отсутствует точная аналитика документа.");
  }
  if (!/^\d+(?:\.\d+)*$/.test(row.account) || !["60", "62"].includes(row.account.split(".")[0])
      || !["asset", "liability"].includes(row.category)) {
    throw new Error("CSV содержит счёт или вид задолженности вне области 60/62.");
  }
  return JSON.stringify([row.account, row.category, row.counterparty, row.contract, row.document]);
}

export function compareTradeDocumentCsv(input: string, scope: {
  organization_id: number; from: string; to: string; rows: ErpTradePosition[];
}): TradeComparison {
  const rows = csvRows(input);
  if (!rows.length || rows[0].join("\u0000") !== EXTERNAL_TRADE_HEADER.join("\u0000")) {
    throw new Error("Нужен нормализованный CSV 1С с точным заголовком шаблона.");
  }
  if (rows.length === 1) throw new Error("CSV 1С не содержит документов.");
  const erp = new Map<string, ErpTradePosition>();
  for (const position of scope.rows) {
    if (!position.analytics_complete || !position.counterparty || !position.contract || !position.document) {
      throw new Error("В ERP есть документы без полной аналитики; сравнение недоступно.");
    }
    const key = identity(position as Position);
    if (erp.has(key)) throw new Error("В ERP есть неоднозначные повторяющиеся документы.");
    validAmounts(position);
    erp.set(key, position);
  }
  const external = new Map<string, Position>();
  for (const cells of rows.slice(1)) {
    if (cells.length !== EXTERNAL_TRADE_HEADER.length) throw new Error("CSV 1С содержит строку с неверным числом колонок.");
    const record = Object.fromEntries(EXTERNAL_TRADE_HEADER.map((field, index) => [field, cells[index]]));
    if (record.source_system !== "1C" || record.organization_id !== String(scope.organization_id)
        || record.period_start !== scope.from || record.period_end !== scope.to) {
      throw new Error("CSV 1С не соответствует выбранному юрлицу, периоду или обозначению источника 1C.");
    }
    const position: Position = {
      account: record.account, category: record.category, counterparty: record.counterparty,
      contract: record.contract, document: record.settlement_document,
      opening_byn: record.opening_byn, debit_byn: record.debit_byn,
      credit_byn: record.credit_byn, closing_byn: record.closing_byn,
    };
    const key = identity(position);
    if (external.has(key)) throw new Error("CSV 1С содержит повторяющийся документ.");
    validAmounts(position);
    external.set(key, position);
  }
  const issues: TradeComparisonIssue[] = [];
  let matched = 0;
  for (const [key, erpRow] of erp) {
    const externalRow = external.get(key) ?? null;
    const id = { account: erpRow.account, category: erpRow.category,
      counterparty: erpRow.counterparty!, contract: erpRow.contract!, document: erpRow.document! };
    if (!externalRow) {
      issues.push({ kind: "missing_in_1c", identity: id, erp: erpRow, external: null, differing_fields: [] });
      continue;
    }
    const differing = amountFields.filter((field) => cents(erpRow[field]) !== cents(externalRow[field]));
    if (differing.length) issues.push({ kind: "amount_difference", identity: id,
      erp: erpRow, external: externalRow, differing_fields: differing });
    else matched += 1;
  }
  for (const [key, externalRow] of external) {
    if (!erp.has(key)) issues.push({ kind: "only_in_1c", identity: externalRow,
      erp: null, external: externalRow, differing_fields: [] });
  }
  return { status: issues.length ? "differences" : "matched", external_rows: external.size,
    erp_rows: erp.size, matched_rows: matched, issues };
}
