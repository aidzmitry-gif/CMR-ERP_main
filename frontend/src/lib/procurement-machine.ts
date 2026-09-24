"use client";

export type Identity = { organization_id: number; principal: string; can_manage: boolean };
export type Organization = { id: number; name: string; unp: string };
export type ProcurementSkuOption = { id: number; code: string; title: string; unit: string };
export type ProcurementSkuOptions = { organization_id: number; items: ProcurementSkuOption[]; truncated: boolean };
export type ProcurementSupplierOption = { id: number; name: string; unp: string };
export type ProcurementSupplierOptions = { organization_id: number; items: ProcurementSupplierOption[]; truncated: boolean };
export type MachineLine = { id: number; sku_code: string; qty: string; goods_value_byn: string; weight: string; volume: string };
export type NewLine = Omit<MachineLine, "id">;
export type MachineOrder = { organization_id: number; id: number; number: string; supplier: string; status: string; eta_date: string | null; freight_byn: string; lines: MachineLine[]; next_after_line_id: number | null };
export type OrderEditHistoryItem = { id: number; changed_at: string; changed_by: string; action: Action; changes: { field: string; before: unknown; after: unknown; before_unknown?: boolean }[] };
export type OrderEditHistory = { organization_id: number; order_id: number; number: string; items: OrderEditHistoryItem[]; next_after_id: number | null };
export type ExpectedLine = { pending_conversion_count: number; order_line_id: number; sku_code: string; ordered: string; accepted: string; warehouse_accepted: string; physical_convertible: string; expected: string; converted: string; convertible: string; expected_reserved: string; free_expected: string; uncovered: string; reservations: { id: number; deal_id: number; demand_id: number | null; document_id: number | null; qty: string; released: string; converted: string; convertible: string }[] };
export type ExpectedOrder = { organization_id: number; order_id: number; lines: ExpectedLine[] };
export type DealDemandCandidate = { demand_id: number; deal_id: number; deal_item_id: number; sku_code: string; qty: string; free_qty: string; document_id: number | null };
export type DealDemandLine = { order_line_id: number; sku_code: string; ordered: string; client_ordered: string; free_for_client: string; candidates: DealDemandCandidate[]; allocations: { id: number; demand_id: number; qty: string }[] };
export type DealDemandOrder = { organization_id: number; order_id: number; lines: DealDemandLine[] };
export type LandedPreview = { organization_id: number; order_id: number; freight_byn: string; lines: { sku_code: string; goods_byn: string; allocated_byn: string; landed_total_byn: string; unit_landed_cost_byn: string }[]; total_goods_byn: string; total_landed_byn: string };
export type Plan = { organization_id: number; order_id: number; principal?: string | null; transport_method_code: string | null; target_arrival_date: string | null; start_date: string | null; total_days: number; milestones: { stage: string; title: string; planned_date: string | null; actual_date: string | null }[]; customer_requirements_status: "unverified"; at_risk: null; required_by: null; required_arrival: null; slack_days: null; at_risk_deals: never[]; schedule_start_in_past: boolean | null };
export type PurchaseChainReceipt = {
  id: number; source_key: string; version: number; status: string;
  posting: { entry_id: number; version: number } | null;
  invoice_reference: string | null; document_date: string | null; operation_date: string | null;
  supplier: string | null; contract: string | null; warehouse: string | null;
  lines: { order_line_id: number | null; sku: string | null; lot: string | null; quantity: string | null; unit: string | null }[];
  physical_acceptance: { receipt_id: number; source_version: number; lines: unknown[]; evidence: string; actor: string; created_at: string }[];
};
export type PurchaseChain = {
  organization_id: number;
  order: { id: number; number: string; supplier: string; status: string; eta_date: string | null; freight_byn: string; lines: { id: number; sku_code: string; quantity: string; goods_value_byn: string }[] };
  request_links: { id: number; request_id: number; ownership_id: number; number: string; supplier: string; item: string; quantity: string; planned_amount: string; stage: string; evidence: string }[];
  receipts: PurchaseChainReceipt[];
  stages: { request: "linked" | "missing"; order: "owned"; incoming_invoice: "posted" | "draft" | "missing"; warehouse: "accepted" | "pending" | "missing" };
  status: "complete" | "partial";
  blockers: string[];
};
export type Action = "add_line" | "delete_line" | "header" | "status" | "plan" | "save";
export type Ack = { organization_id: number; principal: string; order_id: number; action: Action; affected_line_id: number | null; status: string; received_at: string | null };
const prefix = (org: number) => `/api/procurement/organizations/${org}`;
const id = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v) && v > 0 && v <= 2147483647;
const money = (v: unknown): v is string => typeof v === "string" && /^-?\d+(\.\d+)?$/.test(v) && Number.isFinite(Number(v));
export function emptyLine(): NewLine { return { sku_code: "", qty: "1.00", goods_value_byn: "0.00", weight: "0.000", volume: "0.0000" }; }
export function decimalInput(value: string, scale: number, positive = false): string {
  if (!new RegExp(`^(?:0|[1-9][0-9]{0,${13 - scale}})(?:\\.[0-9]{1,${scale}})?$`).test(value) || (positive && !/[1-9]/.test(value))) throw new Error("Укажите точное неотрицательное число с допустимой точностью");
  const [whole, fraction = ""] = value.split("."); return `${whole}.${fraction.padEnd(scale, "0")}`;
}
export class MutationUnknown extends Error {}
export class ReadFailure extends Error { constructor(public status: number) { super(`Не удалось прочитать данные (${status})`); } }
async function read<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new ReadFailure(response.status);
  return response.json();
}
export async function organizations(): Promise<Organization[]> {
  const v = await read<Organization[]>("/api/procurement/receipt-organizations");
  if (!Array.isArray(v) || v.some(x => !id(x.id) || typeof x.name !== "string")) throw new Error("Некорректный список организаций"); return v;
}
export async function fetchProcurementSkus(org: number, search = ""): Promise<ProcurementSkuOptions> {
  const value = await read<ProcurementSkuOptions>(`${prefix(org)}/sku-options?q=${encodeURIComponent(search)}`);
  if (value.organization_id !== org || typeof value.truncated !== "boolean" || !Array.isArray(value.items)
      || value.items.length > 50 || value.items.some((row) => !id(row.id) || !row.code || !row.title || !row.unit
        || typeof row.code !== "string" || typeof row.title !== "string" || typeof row.unit !== "string")) {
    throw new Error("Некорректный справочник номенклатуры закупок");
  }
  return value;
}
export async function fetchProcurementSuppliers(org: number, search = ""): Promise<ProcurementSupplierOptions> {
  const value = await read<ProcurementSupplierOptions>(`${prefix(org)}/supplier-options?q=${encodeURIComponent(search)}`);
  if (value.organization_id !== org || typeof value.truncated !== "boolean" || !Array.isArray(value.items)
      || value.items.length > 50 || value.items.some((row) => !id(row.id) || typeof row.name !== "string" || !row.name
        || typeof row.unp !== "string")) {
    throw new Error("Некорректный справочник поставщиков закупок");
  }
  return value;
}
export async function identity(org: number): Promise<Identity> {
  const v = await read<Identity>(`${prefix(org)}/request-plan-context`);
  if (v.organization_id !== org || typeof v.principal !== "string" || !v.principal || typeof v.can_manage !== "boolean") throw new Error("Не удалось подтвердить пользователя"); return v;
}
export async function fetchOrder(org: number, orderId: number): Promise<MachineOrder> {
  let after = 0; let result: MachineOrder | undefined; const ids = new Set<number>();
  do {
    const p = await read<MachineOrder>(`${prefix(org)}/orders/${orderId}?after_line_id=${after}`);
    if (p.organization_id !== org || p.id !== orderId || !Array.isArray(p.lines) || p.lines.length > 200 || typeof p.number !== "string" || typeof p.supplier !== "string" || !money(p.freight_byn) || !["draft", "ordered", "shipped", "customs", "received", "cancelled"].includes(p.status) || (p.eta_date !== null && typeof p.eta_date !== "string")) throw new Error("Некорректная карточка заказа");
    if (result && ["number", "supplier", "status", "eta_date", "freight_byn"].some(k => p[k as keyof MachineOrder] !== result![k as keyof MachineOrder])) throw new Error("Заказ изменился во время чтения; обновите состав");
    for (const line of p.lines) {
      if (!id(line.id) || line.id <= after || ids.has(line.id) || typeof line.sku_code !== "string" || ![line.qty, line.goods_value_byn, line.weight, line.volume].every(money)) throw new Error("Некорректные строки заказа"); ids.add(line.id);
    }
    const next = p.next_after_line_id;
    if (next !== null && (!id(next) || next <= after || p.lines.length !== 200 || p.lines.at(-1)?.id !== next)) throw new Error("Некорректная пагинация заказа");
    result = result ? { ...p, lines: [...result.lines, ...p.lines] } : p;
    after = next ?? 0;
  } while (after);
  return result!;
}
export async function fetchEditHistory(org: number, orderId: number, afterId = 0): Promise<OrderEditHistory> {
  const value = await read<OrderEditHistory>(`${prefix(org)}/orders/${orderId}/edit-history?after_id=${afterId}`);
  if (value.organization_id !== org || value.order_id !== orderId || typeof value.number !== "string"
      || !Array.isArray(value.items) || value.items.length > 50 || value.items.some((item, index) =>
        !id(item.id) || item.id <= afterId || (index > 0 && item.id <= value.items[index - 1].id)
        || typeof item.changed_at !== "string" || !item.changed_at || typeof item.changed_by !== "string" || !item.changed_by
        || !["add_line", "delete_line", "header", "status", "plan", "save"].includes(item.action)
        || !Array.isArray(item.changes) || item.changes.length === 0 || item.changes.some((change) =>
          typeof change.field !== "string" || !change.field || !("before" in change) || !("after" in change)))
      || (value.next_after_id !== null && (!id(value.next_after_id) || value.items.length !== 50 || value.next_after_id !== value.items.at(-1)?.id))) {
    throw new Error("Некорректная история изменений заказа");
  }
  return value;
}
export async function fetchLandedPreview(org: number, orderId: number): Promise<LandedPreview> {
  const v = await read<LandedPreview>(`${prefix(org)}/orders/${orderId}/landed-preview`);
  if (v.organization_id !== org || v.order_id !== orderId || !Array.isArray(v.lines) || ![v.freight_byn, v.total_goods_byn, v.total_landed_byn].every(money) || v.lines.some(x => typeof x.sku_code !== "string" || ![x.goods_byn, x.allocated_byn, x.landed_total_byn, x.unit_landed_cost_byn].every(money))) throw new Error("Некорректный предпросмотр"); return v;
}
export async function fetchExpectedReservations(org: number, orderId: number): Promise<ExpectedOrder> {
  const v = await read<ExpectedOrder>(`${prefix(org)}/expected-reservations/order/${orderId}`);
  const exact = (x: unknown) => typeof x === "string" && /^(?:0|\d+\.\d{2})$/.test(x) && Number.isFinite(Number(x));
  if (v.organization_id !== org || v.order_id !== orderId || !Array.isArray(v.lines) || v.lines.some(line =>
    !Number.isSafeInteger(line.pending_conversion_count) || line.pending_conversion_count < 0 || !id(line.order_line_id) || typeof line.sku_code !== "string" || ![line.ordered, line.accepted, line.expected,
      line.warehouse_accepted, line.physical_convertible, line.converted, line.convertible, line.expected_reserved, line.free_expected, line.uncovered].every(exact) || !Array.isArray(line.reservations)
    || line.reservations.some(x => !id(x.id) || !id(x.deal_id) || (x.demand_id !== null && !id(x.demand_id))
      || (x.document_id !== null && !id(x.document_id)) || ![x.qty, x.released, x.converted, x.convertible].every(exact)))) {
    throw new Error("Некорректный реестр предварительных резервов");
  }
  return v;
}
export async function fetchDealDemandOrder(org: number, orderId: number): Promise<DealDemandOrder> {
  const v = await read<DealDemandOrder>(`${prefix(org)}/orders/${orderId}/deal-demands`);
  const exact = (x: unknown) => typeof x === "string" && /^(?:0|\d+\.\d{2})$/.test(x) && Number.isFinite(Number(x));
  if (v.organization_id !== org || v.order_id !== orderId || !Array.isArray(v.lines) || v.lines.some(line =>
    !id(line.order_line_id) || typeof line.sku_code !== "string" || ![line.ordered, line.client_ordered, line.free_for_client].every(exact)
    || !Array.isArray(line.candidates) || line.candidates.some(x => !id(x.demand_id) || !id(x.deal_id) || !id(x.deal_item_id)
      || typeof x.sku_code !== "string" || ![x.qty, x.free_qty].every(exact) || (x.document_id !== null && !id(x.document_id)))
    || !Array.isArray(line.allocations) || line.allocations.some(x => !id(x.id) || !id(x.demand_id) || !exact(x.qty)))) {
    throw new Error("Некорректный реестр потребностей закупки");
  }
  return v;
}
function validPlan(v: Plan, org: number, orderId: number) {
  const date = (x: unknown) => x === null || (typeof x === "string" && /^\d{4}-\d{2}-\d{2}$/.test(x));
  return !!v && date(v.target_arrival_date) && date(v.start_date) && Number.isInteger(v.total_days) && v.total_days >= 0 && (v.schedule_start_in_past === null || typeof v.schedule_start_in_past === "boolean") && (v.transport_method_code === null || typeof v.transport_method_code === "string") && v.organization_id === org && v.order_id === orderId && Array.isArray(v.milestones) && v.milestones.every(x => typeof x.stage === "string" && typeof x.title === "string") && v.customer_requirements_status === "unverified" && v.at_risk === null && v.required_by === null && v.required_arrival === null && v.slack_days === null && Array.isArray(v.at_risk_deals) && v.at_risk_deals.length === 0;
}
export async function fetchPlan(org: number, orderId: number): Promise<Plan> {
  const v = await read<Plan>(`${prefix(org)}/orders/${orderId}/plan`); if (!validPlan(v, org, orderId)) throw new Error("Некорректный план заказа"); return v;
}

export async function fetchPurchaseChain(org: number, orderId: number): Promise<PurchaseChain> {
  const v = await read<PurchaseChain>(`${prefix(org)}/orders/${orderId}/chain`);
  const exact = (x: unknown) => typeof x === "string" && /^(?:0|\d+\.\d{2})$/.test(x) && Number.isFinite(Number(x));
  const positive = (x: unknown) => id(x);
  if (v.organization_id !== org || !v.order || v.order.id !== orderId || typeof v.order.number !== "string" ||
      typeof v.order.supplier !== "string" || typeof v.order.status !== "string" || (v.order.eta_date !== null && typeof v.order.eta_date !== "string") ||
      !exact(v.order.freight_byn) || !Array.isArray(v.order.lines) || v.order.lines.some(line =>
        !positive(line.id) || typeof line.sku_code !== "string" || !exact(line.quantity) || !exact(line.goods_value_byn)) ||
      !Array.isArray(v.request_links) || v.request_links.some(row =>
        !positive(row.id) || !positive(row.request_id) || !positive(row.ownership_id) || typeof row.number !== "string" || typeof row.supplier !== "string" ||
        typeof row.item !== "string" || !exact(row.quantity) || !exact(row.planned_amount) || typeof row.stage !== "string" || typeof row.evidence !== "string") ||
      !Array.isArray(v.receipts) || v.receipts.some(row =>
        !positive(row.id) || typeof row.source_key !== "string" || !Number.isSafeInteger(row.version) || row.version < 1 || typeof row.status !== "string" ||
        (row.posting !== null && (!positive(row.posting.entry_id) || !Number.isSafeInteger(row.posting.version) || row.posting.version < 1)) ||
        !Array.isArray(row.lines) || row.lines.some(line => (line.order_line_id !== null && !positive(line.order_line_id)) ||
          (line.sku !== null && typeof line.sku !== "string") || (line.lot !== null && typeof line.lot !== "string") ||
          (line.quantity !== null && !exact(line.quantity)) || (line.unit !== null && typeof line.unit !== "string")) ||
        !Array.isArray(row.physical_acceptance) || row.physical_acceptance.some(item =>
          !positive(item.receipt_id) || !Number.isSafeInteger(item.source_version) || item.source_version < 1 || !Array.isArray(item.lines) ||
          typeof item.evidence !== "string" || typeof item.actor !== "string" || typeof item.created_at !== "string")) ||
      !["linked", "missing"].includes(v.stages?.request) || v.stages?.order !== "owned" ||
      !["posted", "draft", "missing"].includes(v.stages?.incoming_invoice) || !["accepted", "pending", "missing"].includes(v.stages?.warehouse) ||
      !["complete", "partial"].includes(v.status) || !Array.isArray(v.blockers) || v.blockers.some(x => typeof x !== "string")) {
    throw new Error("Некорректная цепочка закупки");
  }
  return v;
}

export type EditCommand = { version: 1; request_key: string; order_id: number; action: Action; payload: Record<string, unknown> };
export type EditOutcome = { version: 1; organization_id: number; principal: string; request_key: string; command_hash: string; order_id: number; action: Action } & ({ outcome: "applied"; ownership_id: number; effect: Record<string, unknown> } | { outcome: "rejected"; code: string; no_business_write: true });
const keys = (v: unknown, expected: string[]): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v) && Object.keys(v).sort().join(",") === [...expected].sort().join(",");
const uuid = (v: unknown) => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v);
const calendar = (v: unknown) => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) && !Number.isNaN(Date.parse(v)) && new Date(v).toISOString().slice(0, 10) === v;
const statuses = ["draft", "ordered", "shipped", "customs", "received", "cancelled"];
const exactDecimal = (v: unknown, scale: number, positive = false) => typeof v === "string" && new RegExp(`^(?:0|[1-9][0-9]{0,${13-scale}})\\.[0-9]{${scale}}$`).test(v) && (!positive || /[1-9]/.test(v));
export function validCommand(v: unknown): v is EditCommand {
  if (!keys(v, ["version", "request_key", "order_id", "action", "payload"]) || v.version !== 1 || !uuid(v.request_key) || !id(v.order_id)) return false;
  const p = v.payload;
  if (v.action === "save") {
    if (!p || typeof p !== "object" || Array.isArray(p)) return false;
    const changes = p as Record<string, unknown>;
    const steps = Object.keys(changes);
    return steps.length > 0 && steps.every(step => ["add_line", "header", "plan", "status"].includes(step)
      && validCommand({ ...v, action: step, payload: changes[step] }));
  }
  if (v.action === "add_line") {
    const base = ["sku_code", "qty", "goods_value_byn", "weight", "volume"];
    const selected = ["sku_id", "sku_title", "sku_unit"];
    return (keys(p, base) || keys(p, [...base, ...selected]))
      && typeof p.sku_code === "string" && p.sku_code.trim() === p.sku_code && p.sku_code.length > 0 && [...p.sku_code].length <= 64 && !p.sku_code.includes("\0")
      && (!("sku_id" in p) || id(p.sku_id) && typeof p.sku_title === "string" && p.sku_title.length > 0 && p.sku_title.length <= 255 && !p.sku_title.includes("\0") && typeof p.sku_unit === "string" && p.sku_unit.length > 0 && p.sku_unit.length <= 16 && !p.sku_unit.includes("\0"))
      && exactDecimal(p.qty, 2, true) && exactDecimal(p.goods_value_byn, 2) && exactDecimal(p.weight, 3) && exactDecimal(p.volume, 4);
  }
  if (v.action === "delete_line") return keys(p, ["line_id"]) && id(p.line_id);
  if (v.action === "status") return keys(p, ["status"]) && typeof p.status === "string" && statuses.includes(p.status);
  if (v.action === "plan") return keys(p, ["transport_method_code", "target_arrival_date"]) && typeof p.transport_method_code === "string" && p.transport_method_code.length > 0 && calendar(p.target_arrival_date);
  if (v.action === "header" && p && typeof p === "object" && !Array.isArray(p)) {
    const fields = p as Record<string, unknown>;
    return Object.keys(fields).length > 0 && Object.entries(fields).every(([k, x]) => k === "freight_byn" ? exactDecimal(x, 2) : k === "eta_date" ? x === null || calendar(x) : k === "supplier_id" ? x === null || id(x) : k === "supplier" && typeof x === "string" && x.trim() === x && [...x].length <= 255 && !x.includes("\0"));
  }
  return false;
}
export function canonical(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(canonical).join(",")}]`;
  if (v && typeof v === "object") return `{${Object.keys(v).sort().map(k => `${JSON.stringify(k)}:${canonical((v as Record<string, unknown>)[k])}`).join(",")}}`;
  return JSON.stringify(v);
}
export async function commandHash(c: EditCommand): Promise<string> {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical(c)));
  return [...new Uint8Array(bytes)].map(x => x.toString(16).padStart(2, "0")).join("");
}
function consistentPlan(e: Record<string, unknown>) {
  const ms = e.milestones as Record<string, unknown>[];
  const stages = ["collection", "payment", "production", "to_cn_warehouse", "to_minsk", "customs"];
  if (ms.length !== stages.length || ms.some((m, i) => m.stage !== stages[i] || m.seq !== i || typeof m.duration_days !== "number" || !Number.isInteger(m.duration_days) || m.duration_days < 0)) return false;
  let cursor = new Date(String(e.target_arrival_date)); let days = 0;
  for (const m of [...ms].reverse()) { if (m.planned_date !== cursor.toISOString().slice(0, 10)) return false; cursor = new Date(cursor.getTime() - Number(m.duration_days) * 86400000); if (Number.isNaN(cursor.getTime())) return false; days += Number(m.duration_days); }
  return days === e.total_days && cursor.toISOString().slice(0, 10) === e.start_date;
}
function validEffect(c: EditCommand, e: Record<string, unknown>, scope: Identity): boolean {
  if (c.action === "save") return keys(e, Object.keys(c.payload)) && Object.entries(c.payload).every(([step, payload]) =>
    !!e[step] && typeof e[step] === "object" && !Array.isArray(e[step])
    && validEffect({ ...c, action: step as Action, payload: payload as Record<string, unknown> }, e[step] as Record<string, unknown>, scope));
  if (c.action === "add_line" || c.action === "delete_line") {
    if (!keys(e, ["line"]) || !keys(e.line, ["id", "sku_code", "qty", "goods_value_byn", "weight", "volume"])) return false;
    const l = e.line;
    if (!id(l.id) || typeof l.sku_code !== "string" || ![l.qty, l.goods_value_byn, l.weight, l.volume].every(money)) return false;
    return c.action === "delete_line" ? l.id === c.payload.line_id : canonical(Object.fromEntries(Object.entries(l).filter(([k]) => k !== "id"))) === canonical(Object.fromEntries(Object.entries(c.payload).filter(([k]) => !["sku_id", "sku_title", "sku_unit"].includes(k))));
  }
  if (c.action === "header") return keys(e, ["before", "after"]) && keys(e.before, Object.keys(c.payload)) && canonical(e.after) === canonical(c.payload) && Object.entries(e.before).every(([k, x]) => k === "freight_byn" ? money(x) : k === "supplier" ? typeof x === "string" : k === "supplier_id" ? x === null || Number.isInteger(x) : x === null || calendar(x));
  if (c.action === "status") return keys(e, ["from", "to", "received_at", "event_ids"]) && typeof e.from === "string" && statuses.includes(e.from) && e.to === c.payload.status && (e.received_at === null || (typeof e.received_at === "string" && /^\d{4}-\d{2}-\d{2}T/.test(e.received_at))) && Array.isArray(e.event_ids) && e.event_ids.every(id) && new Set(e.event_ids).size === e.event_ids.length && (e.event_ids.length > 0) === (e.from !== e.to);
  if (c.action === "plan") return keys(e, ["organization_id", "order_id", "principal", "transport_method_code", "target_arrival_date", "start_date", "total_days", "milestones", "customer_requirements_status", "required_by", "required_arrival", "slack_days", "at_risk", "at_risk_deals", "schedule_start_in_past"]) && validPlan(e as unknown as Plan, scope.organization_id, c.order_id) && e.principal === scope.principal && e.target_arrival_date === c.payload.target_arrival_date && e.transport_method_code === c.payload.transport_method_code && consistentPlan(e) && (e.milestones as Record<string, unknown>[]).every(m => keys(m, ["stage", "title", "seq", "duration_days", "planned_date", "actual_date"]) && Number.isInteger(m.seq) && Number.isInteger(m.duration_days) && (m.planned_date === null || calendar(m.planned_date)) && (m.actual_date === null || calendar(m.actual_date)));
  return false;
}
export async function validOutcome(v: unknown, scope: Identity, c: EditCommand): Promise<boolean> {
  const common = ["version", "organization_id", "principal", "request_key", "command_hash", "order_id", "action", "outcome"];
  if (!v || typeof v !== "object") return false;
  const r = v as EditOutcome;
  if (r.version !== 1 || r.organization_id !== scope.organization_id || r.principal !== scope.principal || r.request_key !== c.request_key || r.order_id !== c.order_id || r.action !== c.action || r.command_hash !== await commandHash(c)) return false;
  if (r.outcome === "rejected") return keys(r, [...common, "code", "no_business_write"]) && r.no_business_write === true && ["command_abandoned", "source_unavailable", "order_not_editable", "line_unavailable", "transition_not_allowed", "transport_method_unavailable", "sku_catalog_changed"].includes(r.code);
  return r.outcome === "applied" && keys(r, [...common, "ownership_id", "effect"]) && id(r.ownership_id) && !!r.effect && typeof r.effect === "object" && validEffect(c, r.effect, scope);
}
export async function sendEdit(scope: Identity, command: EditCommand, mode: "execute" | "reconcile"): Promise<EditOutcome> {
  if (!validCommand(command)) throw new Error("Повреждена сохранённая команда");
  let response: Response; let result: unknown;
  try {
    response = await fetch(`${prefix(scope.organization_id)}/orders/${command.order_id}/edit-commands${mode === "reconcile" ? "/reconcile" : ""}`, { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json", "X-Expected-Organization": String(scope.organization_id), "X-Expected-Principal": scope.principal }, body: JSON.stringify(command) });
    result = await response.json();
  } catch { throw new MutationUnknown("Ответ не подтверждён. Повторите сохранённую команду или выполните сверку."); }
  if ((response.status !== 200 && response.status !== 409) || !(await validOutcome(result, scope, command)) || (response.status === 200) !== ((result as EditOutcome).outcome === "applied")) throw new MutationUnknown(`Нет подтверждённого результата (${response.status}). Сохранённая попытка остаётся открытой.`);
  return result as EditOutcome;
}


export type CustomerDeadlines = { organization_id: number; order_id: number; status: "live_review"; source: "outstanding_expected_reservations"; earliest_required_arrival: string | null; unresolved_deadlines: number; complete_customer_demand: false; at_risk: boolean | null; items: { reservation_id: number; deal_id: number; sku_code: string; outstanding_qty: string; ship_deadline: string | null; required_arrival: string | null; deadline_status: string; at_risk: boolean | null }[] };
export async function fetchCustomerDeadlines(org: number, orderId: number): Promise<CustomerDeadlines> {
  const v = await read<CustomerDeadlines>(`${prefix(org)}/orders/${orderId}/customer-deadlines`);
  const date = (x: unknown) => x === null || typeof x === "string" && /^\d{4}-\d{2}-\d{2}$/.test(x);
  const risk = (x: unknown) => x === null || typeof x === "boolean";
  if (v.organization_id !== org || v.order_id !== orderId || v.status !== "live_review" || v.source !== "outstanding_expected_reservations" || v.complete_customer_demand !== false || !date(v.earliest_required_arrival) || !risk(v.at_risk) || !Number.isInteger(v.unresolved_deadlines) || v.unresolved_deadlines < 0 || !Array.isArray(v.items) || v.items.some(x => !id(x.reservation_id) || !id(x.deal_id) || typeof x.sku_code !== "string" || typeof x.outstanding_qty !== "string" || !/^\d+\.\d{2}$/.test(x.outstanding_qty) || (x.ship_deadline !== null && typeof x.ship_deadline !== "string") || !date(x.required_arrival) || !risk(x.at_risk))) throw new Error("Некорректный обзор клиентских сроков");
  return v;
}
