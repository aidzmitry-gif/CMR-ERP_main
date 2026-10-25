export type OpeningRow = { sku: string; warehouse: string; lot: string; quantity: string; amount_byn: string };
export type OpeningDocument = { request_key: string; opening_date: string; policy_id: number;
  inventory_account: string; counter_account: string; evidence: string; rows: OpeningRow[] };
export type OpeningContext = { organization_id: number; opening_date: string; policy_id: number | null;
  inventory_accounts: { code: string; title: string }[]; counter_accounts: { code: string; title: string }[];
  warehouses: { name: string; title: string }[]; existing_opening_entries: number; physical_stock_updated: false };
export type OpeningResult = { organization_id: number; request_key: string; opening_date: string;
  preview_digest: string; rows: (OpeningRow & { unit: string; sku_title?: string; warehouse_title?: string })[];
  row_count: number; total_byn: string; confirmed: boolean; entry_ids: number[];
  physical_stock_updated: false; cutover_finalized: false };

export class OpeningRequestError extends Error {
  constructor(message: string, public readonly rejected: boolean) { super(message); }
}

/** Five tab-separated columns, exactly as copied from Excel. Never parse money as float. */
export function pasteOpeningRows(text: string): OpeningRow[] {
  const rows = text.trim().split(/\r?\n/).map((line, index) => {
    const cells = line.split("\t").map(v => v.trim());
    if (cells.length !== 5 || cells.some(v => !v)) throw new Error(`Строка ${index + 1}: нужны пять заполненных столбцов`);
    const [sku, warehouse, lot, quantity, amount] = cells;
    const decimal = (value: string, scale: number) => {
      const normalized = value.replace(/[\u00a0\u202f ]/g, "").replace(",", ".");
      if (!new RegExp(`^\\d+(?:\\.\\d{1,${scale}})?$`).test(normalized) || !/[1-9]/.test(normalized))
        throw new Error(`Строка ${index + 1}: неверное положительное число`);
      return normalized;
    };
    return { sku, warehouse, lot, quantity: decimal(quantity, 6), amount_byn: decimal(amount, 2) };
  });
  if (rows.length > 5000) throw new Error("В одном документе допускается до 5000 строк");
  return rows;
}

export function readOpeningDraft(text: string, org: number): OpeningDocument {
  const data = JSON.parse(text);
  const doc = data?.document;
  if (data?.format !== "opening-stock-draft-v1" || data.organization_id !== org || !doc
    || typeof doc.request_key !== "string" || !/^[0-9a-f-]{36}$/i.test(doc.request_key)
    || typeof doc.opening_date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(doc.opening_date)
    || !Number.isSafeInteger(doc.policy_id) || doc.policy_id < 0
    || [doc.inventory_account, doc.counter_account, doc.evidence].some(v => typeof v !== "string")
    || !Array.isArray(doc.rows) || doc.rows.length < 1 || doc.rows.length > 5000
    || doc.rows.some((r: OpeningRow) => !r || [r.sku, r.warehouse, r.lot, r.quantity, r.amount_byn]
      .some(v => typeof v !== "string"))) throw new Error("Файл черновика повреждён или относится к другой организации");
  return doc;
}

export async function openingRequest<T>(org: number, path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/accounting/organizations/${org}/opening-stock/${path}`, {
    method: body === undefined ? "GET" : "POST", cache: "no-store",
    ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new OpeningRequestError(typeof data?.detail === "string" ? data.detail : `Не удалось выполнить запрос (${response.status})`, [400, 401, 403, 404, 409, 422].includes(response.status));
  if (data?.organization_id !== org || data.physical_stock_updated !== false)
    throw new Error("Ответ не соответствует организации или режиму ввода остатков");
  if (path.startsWith("context")) {
    if (!(data.policy_id === null || Number.isSafeInteger(data.policy_id) && data.policy_id > 0)
      || !Number.isSafeInteger(data.existing_opening_entries) || data.existing_opening_entries < 0
      || ![data.inventory_accounts, data.counter_accounts].every(items => Array.isArray(items)
        && items.every(a => a && typeof a.code === "string" && typeof a.title === "string"))
      || !Array.isArray(data.warehouses) || data.warehouses.some((w: { name?: unknown; title?: unknown }) => !w || typeof w.name !== "string" || typeof w.title !== "string"))
      throw new Error("Ответ настройки начальных остатков повреждён");
  } else if (!Number.isSafeInteger(data.row_count) || data.row_count < 1 || data.row_count > 5000
    || !Array.isArray(data.rows) || data.rows.length !== data.row_count || data.cutover_finalized !== false
    || typeof data.confirmed !== "boolean" || typeof data.total_byn !== "string" || !/^\d+\.\d{2}$/.test(data.total_byn)
    || !Array.isArray(data.entry_ids) || data.entry_ids.some((id: unknown) => !Number.isSafeInteger(id) || Number(id) <= 0)
    || data.rows.some((r: OpeningRow & { unit?: unknown }) => !r || [r.sku, r.warehouse, r.lot, r.quantity, r.amount_byn, r.unit].some(v => typeof v !== "string" || !v)))
    throw new Error("Ответ проверки начальных остатков повреждён");
  return data as T;
}
