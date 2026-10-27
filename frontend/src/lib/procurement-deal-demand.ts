"use client";

import type { DealDemandCandidate } from "./procurement-machine";

export type DealDemand = {
  id: number;
  organization_id: number;
  deal_id: number;
  deal_item_id: number;
  sku_id: number;
  sku_code: string;
  qty: string;
  ordered_qty: string;
  free_qty: string;
  document_id: number | null;
  request_key: string;
  allocations: { id: number; order_id: number; order_line_id: number; qty: string }[];
};

const exact = (value: unknown) =>
  typeof value === "string" && /^(?:0|\d+\.\d{2})$/.test(value) && Number.isFinite(Number(value));
const positiveId = (value: unknown): value is number =>
  typeof value === "number" && Number.isInteger(value) && value > 0 && value <= 2147483647;
const uuid = () => crypto.randomUUID();
const requestKey = (value: unknown): value is string =>
  typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);

function validDemand(value: unknown, org: number, dealId: number): value is DealDemand {
  if (!value || typeof value !== "object") return false;
  const row = value as DealDemand;
  return row.organization_id === org && row.deal_id === dealId && positiveId(row.id) && positiveId(row.deal_item_id)
    && positiveId(row.sku_id) && typeof row.sku_code === "string"
    && [row.qty, row.ordered_qty, row.free_qty].every(exact)
    && (row.document_id === null || positiveId(row.document_id))
    && typeof row.request_key === "string" && Array.isArray(row.allocations)
    && row.allocations.every(x => positiveId(x.id) && positiveId(x.order_id) && positiveId(x.order_line_id) && exact(x.qty));
}

export async function fetchDealDemands(org: number, dealId: number): Promise<DealDemand[]> {
  const response = await fetch(`/api/procurement/organizations/${org}/deals/${dealId}/demands`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Не удалось прочитать потребности закупки (${response.status})`);
  const body = await response.json() as { organization_id?: unknown; deal_id?: unknown; demands?: unknown };
  if (body.organization_id !== org || body.deal_id !== dealId || !Array.isArray(body.demands)
      || body.demands.some(row => !validDemand(row, org, dealId))) throw new Error("Некорректный реестр потребностей закупки");
  return body.demands as DealDemand[];
}

export async function createDealDemand(
  org: number,
  dealId: number,
  dealItemId: number,
  qty: string,
  /** Reuse after an uncertain response so the server can return its immutable receipt. */
  key = uuid(),
): Promise<DealDemand> {
  if (!positiveId(org) || !positiveId(dealId) || !positiveId(dealItemId) || !/^\d+\.\d{2}$/.test(qty) || !requestKey(key)) {
    throw new Error("Некорректное основание потребности закупки");
  }
  const response = await fetch(`/api/procurement/organizations/${org}/deals/${dealId}/demands`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      deal_item_id: dealItemId,
      qty,
      request_key: key,
      evidence: `CRM deal ${dealId}: order the unavailable item`,
    }),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok || !validDemand(body, org, dealId)) throw new Error(`Не удалось создать потребность закупки (${response.status})`);
  return body;
}

export type DealDemandAllocationScope = { organization_id: number; principal: string; order_id: number };
export type DealDemandAllocationCommand = {
  order_id: number;
  order_line_id: number;
  qty: string;
  request_key: string;
  evidence: string;
};
export type PendingDealDemandAllocation = {
  version: 1;
  scope: DealDemandAllocationScope;
  demand_id: number;
  sku_code: string;
  command: DealDemandAllocationCommand;
  body: string;
};
export type DealDemandAllocationReceipt = DealDemand & {
  replayed: boolean;
  allocation_request_key: string;
  allocation: { id: number; demand_id: number; order_id: number; order_line_id: number; sku_code: string; qty: string };
};

export class DealDemandError extends Error {
  constructor(message: string, readonly status?: number, readonly uncertain = false) { super(message); }
}

const allocationUuid = (value: unknown): value is string =>
  typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
const allocationQty = (value: unknown): value is string =>
  typeof value === "string" && /^(?:0|[1-9]\d{0,11})\.\d{2}$/.test(value) && Number(value) > 0;
const allocationUnits = (value: string) => {
  const [whole, fraction] = value.split(".");
  return BigInt(whole) * 100n + BigInt(fraction);
};
const allocationKey = (scope: DealDemandAllocationScope, demandId: number, lineId: number) =>
  `erp-deal-demand-allocation-v1:${scope.organization_id}:${scope.principal}:${scope.order_id}:${demandId}:${lineId}`;

function validatePendingAllocation(value: unknown): value is PendingDealDemandAllocation {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as PendingDealDemandAllocation;
  const s = row.scope;
  const c = row.command;
  return row.version === 1 && !!s && positiveId(s.organization_id) && typeof s.principal === "string" && !!s.principal
    && positiveId(s.order_id) && positiveId(row.demand_id) && typeof row.sku_code === "string" && !!row.sku_code
    && !!c && c.order_id === s.order_id && positiveId(c.order_line_id) && allocationQty(c.qty) && allocationUuid(c.request_key)
    && typeof c.evidence === "string" && c.evidence.length > 0 && c.evidence.length <= 1000
    && row.body === JSON.stringify(c);
}

export const dealDemandAllocationStorageKey = (scope: DealDemandAllocationScope, demandId: number, lineId: number) =>
  allocationKey(scope, demandId, lineId);

export function saveDealDemandAllocation(pending: PendingDealDemandAllocation): void {
  if (!validatePendingAllocation(pending)) throw new DealDemandError("Сохранённая команда резерва повреждена.");
  const key = allocationKey(pending.scope, pending.demand_id, pending.command.order_line_id);
  const raw = JSON.stringify(pending);
  try {
    sessionStorage.setItem(key, raw);
    if (sessionStorage.getItem(key) !== raw) throw new Error();
  } catch {
    throw new DealDemandError("Не удалось сохранить команду резерва. Запрос не отправлен.");
  }
}

export function loadDealDemandAllocation(
  scope: DealDemandAllocationScope,
  demandId: number,
  lineId: number,
): PendingDealDemandAllocation | null {
  const raw = sessionStorage.getItem(allocationKey(scope, demandId, lineId));
  if (!raw) return null;
  try {
    const pending: unknown = JSON.parse(raw);
    if (!validatePendingAllocation(pending)) throw new Error();
    const row = pending as PendingDealDemandAllocation;
    if (row.scope.organization_id !== scope.organization_id || row.scope.principal !== scope.principal
      || row.scope.order_id !== scope.order_id || row.demand_id !== demandId || row.command.order_line_id !== lineId) throw new Error();
    return row;
  } catch {
    throw new DealDemandError("Сохранённая команда резерва повреждена. Сначала проверьте остатки заказа.");
  }
}

export function clearDealDemandAllocation(pending: PendingDealDemandAllocation): void {
  if (!validatePendingAllocation(pending)) throw new DealDemandError("Сохранённая команда резерва повреждена.");
  const key = allocationKey(pending.scope, pending.demand_id, pending.command.order_line_id);
  try {
    if (sessionStorage.getItem(key) === JSON.stringify(pending)) sessionStorage.removeItem(key);
  } catch {
    throw new DealDemandError("Не удалось закрыть сохранённую команду резерва.");
  }
}

function validAllocationReceipt(value: unknown, pending: PendingDealDemandAllocation): value is DealDemandAllocationReceipt {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as DealDemandAllocationReceipt;
  const a = row.allocation;
  return typeof row.replayed === "boolean" && row.allocation_request_key === pending.command.request_key
    && !!a && positiveId(a.id) && a.demand_id === pending.demand_id && a.order_id === pending.scope.order_id
    && a.order_line_id === pending.command.order_line_id && a.sku_code === pending.sku_code && a.qty === pending.command.qty
    && validDemand(row, pending.scope.organization_id, row.deal_id);
}

export async function allocateDealDemand(
  scope: DealDemandAllocationScope,
  candidate: DealDemandCandidate,
  orderLineId: number,
  qty: string,
): Promise<DealDemandAllocationReceipt> {
  if (!positiveId(scope.organization_id) || !scope.principal || !positiveId(scope.order_id)
    || !positiveId(orderLineId) || !positiveId(candidate.demand_id) || !allocationQty(qty)
    || candidate.free_qty === "0.00" || !allocationQty(candidate.free_qty) || allocationUnits(qty) > allocationUnits(candidate.free_qty)) {
    throw new DealDemandError("Количество предварительного резерва изменилось. Обновите заказ.");
  }
  let pending = loadDealDemandAllocation(scope, candidate.demand_id, orderLineId);
  if (pending && (pending.sku_code !== candidate.sku_code || pending.command.qty !== qty)) {
    throw new DealDemandError("Для этой строки уже сохранена другая команда резерва. Сначала завершите или закройте её.");
  }
  if (!pending) {
    const command: DealDemandAllocationCommand = {
      order_id: scope.order_id,
      order_line_id: orderLineId,
      qty,
      request_key: crypto.randomUUID(),
      evidence: `Supplier order ${scope.order_id}: assign expected quantity to CRM demand ${candidate.demand_id}`,
    };
    pending = { version: 1, scope, demand_id: candidate.demand_id, sku_code: candidate.sku_code, command, body: JSON.stringify(command) };
    saveDealDemandAllocation(pending);
  }
  let response: Response;
  let body: unknown;
  try {
    response = await fetch(`/api/procurement/organizations/${scope.organization_id}/demands/${pending.demand_id}/allocations`, {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-Expected-Organization": String(scope.organization_id),
        "X-Expected-Principal": scope.principal,
      },
      body: pending.body,
    });
    body = await response.json().catch(() => null);
  } catch {
    throw new DealDemandError("Связь прервана. Сохранённая команда резерва оставлена для повторной проверки.", undefined, true);
  }
  if (!response.ok) {
    throw new DealDemandError(`Резерв не принят сервером (${response.status}). Проверьте остатки и сохранённую команду.`, response.status);
  }
  if (!validAllocationReceipt(body, pending)) {
    throw new DealDemandError("Ответ не подтверждает выбранный резерв. Сохранённая команда оставлена для сверки.", response.status, true);
  }
  clearDealDemandAllocation(pending);
  return body;
}
