// Клиентский API-слой логистики: тонкие типизированные обёртки над `/api/logistics/*`
// (прокси добавляет роль и переадресует на backend). Все фетчи graceful: при недоступном
// или пустом backend возвращают безопасный fallback ([] / null), чтобы UI не падал.
// Деньги в ответах — BYN (форматируются в компонентах через `formatByn`).

import type { Bid as DomainBid, ScoreMetrics } from "@/lib/logistics-domain";
import type { FunnelStage } from "@/lib/types";

async function getJson<T>(path: string, fallback: T): Promise<T> {
  try {
    const res = await fetch(`/api${path}`, { cache: "no-store" });
    if (!res.ok) return fallback;
    return (await res.json()) as T;
  } catch {
    return fallback;
  }
}

async function postJson<T>(path: string, body: unknown, fallback: T): Promise<T> {
  try {
    const res = await fetch(`/api${path}`, {
      method: "POST",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!res.ok) return fallback;
    return (await res.json()) as T;
  } catch {
    return fallback;
  }
}

async function patchJson<T>(path: string, body: unknown, fallback: T): Promise<T> {
  try {
    const res = await fetch(`/api${path}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) return fallback;
    return (await res.json()) as T;
  } catch {
    return fallback;
  }
}

// ─────────────────────────────── Доставка / дашборд ───────────────────────────────

export interface Shipment {
  id: number;
  number: string;
  customer: string;
  address: string;
  route_from: string;
  route_to: string;
  carrier: string;
  carrier_code: string;
  cargo: string;
  weight_kg: number;
  amount: number;
  status: string;
  tracking_status?: string;
  eta?: string;
}

export interface CostByCarrier {
  carrier: string;
  shipments: number;
  cost: number;
}

export interface Dashboard {
  in_transit: number;
  delivery_in_transit: number;
  import_in_transit: number;
  at_customs: number;
  delivered_total: number;
  avg_delivery_days: number;
  on_time_pct: number;
  logistics_cost: number;
  shipping_cost_company: number;
  carriers: string[];
  cost_by_carrier: CostByCarrier[];
}

export interface Costs {
  total: number;
  company: number;
  client: number;
  import_cost: number;
  by_carrier: CostByCarrier[];
}

export const fetchShipments = () => getJson<Shipment[]>("/logistics/shipments", []);
export const fetchDashboard = () => getJson<Dashboard | null>("/logistics/dashboard", null);
export const fetchCosts = () => getJson<Costs | null>("/logistics/costs", null);

/** Сменить главный статус доставки (planned/assigned/in_transit/delivered). */
export const patchShipmentStatus = (id: number, status: string) =>
  patchJson<Shipment | null>(`/logistics/shipments/${id}`, { status }, null);

/** Обновить tracking_status (текст) + ETA + трек-номер от перевозчика. */
export interface TrackingPatch {
  tracking_status: string;
  eta?: string | null;
  tracking_no?: string | null;
}
export const patchShipmentTracking = (id: number, patch: TrackingPatch) =>
  patchJson<Shipment | null>(`/logistics/shipments/${id}/tracking`, patch, null);

// ─────────────────────────────── Импорт из Китая (информационный) ───────────────────────────────
// Только наблюдение цепочки (события import.*); приёмка на склад/остатки — НЕ здесь
// (это procurement→wms, двойной учёт запрещён).

export interface ImportShipment {
  id: number;
  number: string;
  supplier: string;
  flag: string;
  container_no: string;
  route: string;
  incoterms: string;
  mode: string;
  cargo: string;
  qty: number;
  amount: number;
  priority: string;
  owner: string;
  stage: string;
  customs_status: string;
  eta?: string | null;
  po_ref: string;
}

// Доска импорта = универсальная воронка ядра (FunnelBoardOut: стадии-колонки с карточками).
export interface ImportBoard {
  stages: FunnelStage[];
}

export const fetchImports = () => getJson<ImportShipment[]>("/logistics/imports", []);
export const fetchImportBoard = () => getJson<ImportBoard | null>("/logistics/imports/board", null);

export interface ImportStagePatch {
  stage: string;
  customs_status?: string | null;
}
/** ИНФО-смена стадии импорта. Склад (warehouse) — это лишь отметка для дашборда;
 *  оприходование делает wms на procurement.received. Двойного учёта НЕТ. */
export const patchImportStage = (id: number, patch: ImportStagePatch) =>
  patchJson<ImportShipment | null>(`/logistics/imports/${id}`, patch, null);

// ─────────────────────────────── Тарифы / зоны ───────────────────────────────

export interface Zone {
  id: number;
  code: string;
  name: string;
  coverage: string;
  cities: string[];
  sla_days_min: number;
  sla_days_max: number;
}

export interface CarrierTariff {
  carrier_code: string;
  zone_code: string;
  price_w5: number;
  price_w10: number;
  price_w30: number;
  over30_per_kg: number;
  pickup_fee: number;
  cod_pct: number;
  insurance_pct: number;
  effective_from?: string;
}

export const fetchZones = () => getJson<Zone[]>("/logistics/zones", []);
export const seedZones = () => postJson<Zone[]>("/logistics/zones/seed", undefined, []);
export const fetchTariffs = (zone: string) =>
  getJson<CarrierTariff[]>(`/logistics/carrier-tariffs?zone=${encodeURIComponent(zone)}`, []);
export const seedTariffs = () =>
  postJson<CarrierTariff[]>("/logistics/carrier-tariffs/seed", undefined, []);

// ─────────────────────────────── Перевозчики / парк ───────────────────────────────

export interface Carrier {
  id: number;
  name: string;
  code: string;
  kind: string;
  mode: string;
  on_time_pct: number;
  avg_days: number;
  shipments_count: number;
  active: boolean;
}

export interface Vehicle {
  vehicle_class: string;
  capacity_kg: number;
  volume_m3: number;
  temp_control: boolean;
  count: number;
}

export interface CargoCapability {
  category: string;
  adr: boolean;
  oversize: boolean;
  max_weight_kg: number;
  max_dim_cm: number;
}

export interface EligibleCarrier {
  carrier_code: string;
  carrier: string;
  vehicle_class: string;
  capacity_kg: number;
}

export const fetchCarriers = () => getJson<Carrier[]>("/logistics/carriers", []);
export const seedCarriers = () => postJson<Carrier[]>("/logistics/carriers/seed", undefined, []);
export const seedFleet = () => postJson<unknown>("/logistics/fleet/seed", undefined, null);
export const fetchVehicles = (code: string) =>
  getJson<Vehicle[]>(`/logistics/carriers/${encodeURIComponent(code)}/vehicles`, []);
export const fetchCargoCapabilities = (code: string) =>
  getJson<CargoCapability[]>(`/logistics/carriers/${encodeURIComponent(code)}/cargo-capabilities`, []);

export interface EligibleQuery {
  weight_kg?: number;
  category?: string;
  needs_temp?: boolean;
  max_dim_cm?: number;
  adr?: boolean;
}

export function fetchEligible(q: EligibleQuery): Promise<EligibleCarrier[]> {
  const params = new URLSearchParams();
  if (q.weight_kg != null) params.set("weight_kg", String(q.weight_kg));
  if (q.category) params.set("category", q.category);
  if (q.needs_temp) params.set("needs_temp", "true");
  if (q.max_dim_cm != null) params.set("max_dim_cm", String(q.max_dim_cm));
  if (q.adr) params.set("adr", "true");
  return getJson<EligibleCarrier[]>(`/logistics/carriers/eligible?${params.toString()}`, []);
}

// ─────────────────────────────── Scorecard ───────────────────────────────

export interface Scorecard extends ScoreMetrics {
  carrier_code: string;
  period: string;
  cost_per_delivery: number;
  shipments: number;
  score: number;
  grade: string;
}

export const fetchScorecard = (period: string) =>
  getJson<Scorecard[]>(`/logistics/carriers/scorecard?period=${encodeURIComponent(period)}`, []);
export const seedScorecard = () =>
  postJson<Scorecard[]>("/logistics/carriers/scorecard/seed", undefined, []);
export const recomputeScorecard = () =>
  postJson<Scorecard[]>("/logistics/carriers/scorecard/recompute", undefined, []);

export interface ScorecardMetricsPatch {
  otd_pct?: number;
  otif_pct?: number;
  damage_free_pct?: number;
  billing_accuracy_pct?: number;
  claims_ratio_pct?: number;
  shipments?: number;
  cost_per_delivery?: number;
}
export const patchScorecardMetrics = (
  carrierCode: string,
  period: string,
  patch: ScorecardMetricsPatch,
) =>
  patchJson<Scorecard | null>(
    `/logistics/carriers/scorecard/${encodeURIComponent(carrierCode)}?period=${encodeURIComponent(period)}`,
    patch,
    null,
  );

// ─────────────────────────────── Аудит счетов ───────────────────────────────

export interface AuditEntry {
  id: number;
  shipment_code: string;
  carrier_code: string;
  invoice_amount: number;
  expected_amount: number;
  variance: number;
  reason: string;
  status: string;
}

export interface AuditReport {
  period: string;
  checked: number;
  discrepancies: number;
  to_recover: number;
  items: AuditEntry[];
}

export const fetchAudit = (period: string) =>
  getJson<AuditReport | null>(`/logistics/costs/audit?period=${encodeURIComponent(period)}`, null);
export const seedAudit = () =>
  postJson<AuditEntry[]>("/logistics/costs/audit/seed", undefined, []);

export interface AuditEntryCreate {
  shipment_code: string;
  carrier_code: string;
  invoice_amount: number;
  expected_amount?: number | null;   // если не задан — считается из тарифа (zone_code+weight_kg)
  zone_code?: string;
  weight_kg?: number;
  reason?: string;
}
/** Зарегистрировать счёт перевозчика. На variance>0 бэк эмитит freight.audit_refund → finance. */
export const createAuditEntry = (payload: AuditEntryCreate) =>
  postJson<AuditEntry | null>("/logistics/costs/audit", payload, null);

// ─────────────────────────────── Тендер (RFQ) ───────────────────────────────

export interface Rfq {
  id: number;
  number: string;
  cargo: string;
  weight_kg: number;
  category: string;
  route_from: string;
  route_to: string;
  zone_code: string;
  status: string;
  office_doc_ref?: string;
  created_by?: string;
  deadline?: string;
  awarded_carrier_code?: string;
  awarded_price?: number;
  shipment_id?: number;
}

export interface Invite {
  id: number;
  rfq_id: number;
  carrier_code: string;
  channel: string;
  status: string;
  token?: string;          // секрет публичной ссылки на подачу ставки
  notified_at?: string | null;
  detail?: string;         // результат уведомления (журнал рассылки)
}

export interface Bid extends DomainBid {
  id: number;
  rfq_id: number;
  vehicle_class: string;
  valid_until?: string;
  comment?: string;
  round: number;
  is_best: boolean;
  value_score?: number;     // best-fit: компромисс цена↔качество ∈ [0, 1] (из /bids/ranked)
  is_best_value?: boolean;   // лучший по соотношению цена/качество (не только по цене)
}

export interface TenderRecommendation {
  cheapest: Bid;
  best_value: Bid;
  reliability_premium: number;   // доплата best_value к самому дешёвому (цена надёжности)
  same_carrier: boolean;
  rationale: string;
  median_price?: number;             // медиана ставок (опорная цена тендера)
  cheapest_deviation_pct?: number;    // на сколько % дешевле медианы самая дешёвая (≥ 0)
  dumping_risk?: boolean;             // флаг: подозрительно дёшево (риск срыва/демпинга)
}

export interface AwardResult {
  rfq_id: number;
  status: string;
  carrier_code: string;
  carrier: string;
  price: number;
  shipment_id: number;
  shipment_number: string;
}

export const fetchRfqs = () => getJson<Rfq[]>("/logistics/rfqs", []);
export const fetchRfq = (id: number) => getJson<Rfq | null>(`/logistics/rfqs/${id}`, null);
export const fetchInvites = (id: number) =>
  getJson<Invite[]>(`/logistics/rfqs/${id}/invites`, []);
export const fetchBids = (id: number) => getJson<Bid[]>(`/logistics/rfqs/${id}/bids`, []);
export const fetchRankedBids = (id: number) =>
  getJson<Bid[]>(`/logistics/rfqs/${id}/bids/ranked`, []);
export const fetchRecommendation = (id: number) =>
  getJson<TenderRecommendation | null>(`/logistics/rfqs/${id}/recommendation`, null);
export const seedRfq = () => postJson<Rfq | null>("/logistics/rfqs/seed", undefined, null);

export interface BroadcastResult {
  rfq_id: number;
  status: string;
  invited: number;
  notified?: number;       // фактически уведомлено по контакту (без skip)
  carriers: string[];
}

export const broadcastRfq = (id: number) =>
  postJson<BroadcastResult | null>(`/logistics/rfqs/${id}/broadcast`, undefined, null);
export type AwardStrategy = "cheapest" | "best_value";

export const awardRfq = (id: number, carrierCode?: string, strategy: AwardStrategy = "cheapest") =>
  postJson<AwardResult | null>(
    `/logistics/rfqs/${id}/award`,
    carrierCode ? { carrier_code: carrierCode } : { strategy },
    null,
  );

// ─────────────────────────────── Аналитика стоимости (cost-insights) ───────────────────────────────

export interface ZoneCostInsight {
  zone_code: string;
  zone_name: string;
  carriers: number;
  cheapest_carrier: string;
  cheapest_carrier_name: string;
  cheapest_total: number;
  avg_total: number;
  max_total: number;
  spread_pct: number;
}

export interface TenderSaving {
  rfq_number: string;
  route: string;
  carrier: string;
  baseline: number;
  awarded: number;
  saved: number;
  saved_pct: number;
}

export interface CostInsights {
  reference_weight_kg: number;
  zones: ZoneCostInsight[];
  potential_savings: number;
  best_savings_zone: string;
  tender_savings_total: number;
  tenders: TenderSaving[];
  audit_to_recover: number;
  recommendations: string[];
}

export const fetchCostInsights = (weightKg = 30) =>
  getJson<CostInsights | null>(`/logistics/cost-insights?weight_kg=${weightKg}`, null);
