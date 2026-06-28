// Чистая доменная логика логистики (без зависимостей от React/fetch) — тестируется
// отдельно (logistics-domain.test.ts). Деньги здесь — голые числа; форматирование в
// BYN делает слой компонентов через `formatByn`.

/** Округление до 2 знаков; нормализует −0 → 0 (важно для строгого toBe в тестах). */
function round2(value: number): number {
  const r = Math.round(value * 100) / 100;
  return r === 0 ? 0 : r;
}

// ─────────────────────────────── Тарифы ───────────────────────────────

export interface TariffRates {
  price_w5: number;
  price_w10: number;
  price_w30: number;
  over30_per_kg: number;
  pickup_fee: number;
  cod_pct: number;
  insurance_pct: number;
}

/** Цена за вес по весовой вилке тарифа (без сборов). */
export function tariffWeightPrice(rates: TariffRates, weightKg: number): number {
  if (weightKg <= 0) return 0;
  if (weightKg <= 5) return rates.price_w5;
  if (weightKg <= 10) return rates.price_w10;
  if (weightKg <= 30) return rates.price_w30;
  return round2(rates.price_w30 + (weightKg - 30) * rates.over30_per_kg);
}

export interface QuoteOptions {
  /** объявленная ценность груза — база для страховки */
  declaredValue?: number;
  /** наложенный платёж (COD) */
  cod?: boolean;
}

/** Полная котировка: фрахт (вес + забор) + страховка + COD-наценка. */
export function quoteTariff(rates: TariffRates, weightKg: number, opts: QuoteOptions = {}): number {
  const freight = tariffWeightPrice(rates, weightKg) + rates.pickup_fee;
  const insurance = opts.declaredValue ? (opts.declaredValue * rates.insurance_pct) / 100 : 0;
  const cod = opts.cod ? (freight * rates.cod_pct) / 100 : 0;
  return round2(freight + insurance + cod);
}

// ─────────────────────────────── Тендер (ставки) ───────────────────────────────

export interface Bid {
  carrier_code: string;
  carrier: string;
  price: number;
  eta_days: number;
}

/** Лучшая ставка: минимальная цена, при равенстве — меньший срок. null для пустого списка. */
export function bestBid<T extends Bid>(bids: T[]): T | null {
  if (bids.length === 0) return null;
  return bids.reduce((best, b) =>
    b.price < best.price || (b.price === best.price && b.eta_days < best.eta_days) ? b : best,
  );
}

/** Копия списка, отсортированная по цене ↑, затем по сроку ↑ (исходный массив не мутируется). */
export function rankBids<T extends Bid>(bids: T[]): T[] {
  return [...bids].sort((a, b) => a.price - b.price || a.eta_days - b.eta_days);
}

/** Экономия от конкуренции: разрыв между худшей и лучшей ценой (0, если ставок < 2). */
export function bidSavings(bids: Bid[]): number {
  if (bids.length < 2) return 0;
  const prices = bids.map((b) => b.price);
  return round2(Math.max(...prices) - Math.min(...prices));
}

/** Порог «подозрительно дёшево»: ≥25% ниже медианы при ≥3 ставках = риск демпинга. */
export const DUMPING_THRESHOLD_PCT = 25;
export const DUMPING_MIN_BIDS = 3;

function median(values: number[]): number {
  if (values.length === 0) return 0;
  const s = [...values].sort((a, b) => a - b);
  const n = s.length;
  const mid = Math.floor(n / 2);
  return n % 2 ? s[mid] : round2((s[mid - 1] + s[mid]) / 2);
}

export interface BidRisk {
  median: number;
  deviationPct: number;
  isSuspiciouslyCheap: boolean;
}

/** Риск-признаки ставки: дельта от медианы (% дешевле = +) + флаг демпинга.
 *  Зеркало backend `pricing.bid_risk` (формула и пороги совпадают). */
export function bidRisk(bid: Bid, all: Bid[]): BidRisk {
  const prices = all.map((b) => b.price).filter((p) => p > 0);
  const m = median(prices);
  if (m <= 0 || bid.price <= 0) return { median: m, deviationPct: 0, isSuspiciouslyCheap: false };
  const deviationPct = round2(((m - bid.price) / m) * 100);
  return {
    median: m,
    deviationPct,
    isSuspiciouslyCheap:
      prices.length >= DUMPING_MIN_BIDS && deviationPct >= DUMPING_THRESHOLD_PCT,
  };
}

// ─────────────────────────────── Scorecard перевозчика ───────────────────────────────

export interface ScoreMetrics {
  otd_pct: number;
  otif_pct: number;
  damage_free_pct: number;
  billing_accuracy_pct: number;
  claims_ratio_pct: number;
}

const SCORE_WEIGHTS = { otd: 0.35, otif: 0.25, damage: 0.15, billing: 0.15, claims: 0.1 };

/** Взвешенная оценка 0..100 (claims инвертируется: меньше претензий → выше балл). */
export function computeScorecardScore(m: ScoreMetrics): number {
  const score =
    m.otd_pct * SCORE_WEIGHTS.otd +
    m.otif_pct * SCORE_WEIGHTS.otif +
    m.damage_free_pct * SCORE_WEIGHTS.damage +
    m.billing_accuracy_pct * SCORE_WEIGHTS.billing +
    (100 - m.claims_ratio_pct) * SCORE_WEIGHTS.claims;
  return Math.round(score * 10) / 10;
}

export type Grade = "A" | "B" | "C";

/** Грейд по баллу: ≥90 → A, ≥75 → B, иначе C. */
export function scoreGrade(score: number): Grade {
  if (score >= 90) return "A";
  if (score >= 75) return "B";
  return "C";
}

// ─────────────────────────────── Аудит счетов ───────────────────────────────

export interface AuditItem {
  invoice_amount: number;
  expected_amount: number;
}

/** Отклонение счёта от ожидаемого: > 0 — переплата (к возврату). */
export function auditVariance(invoice: number, expected: number): number {
  return round2(invoice - expected);
}

export interface AuditSummary {
  checked: number;
  discrepancies: number;
  toRecover: number;
}

/** Свод аудита: сколько проверено, сколько расхождений, сколько к возврату (только переплаты). */
export function auditSummary(items: AuditItem[]): AuditSummary {
  let discrepancies = 0;
  let toRecover = 0;
  for (const it of items) {
    const v = auditVariance(it.invoice_amount, it.expected_amount);
    if (v !== 0) discrepancies += 1;
    if (v > 0) toRecover = round2(toRecover + v);
  }
  return { checked: items.length, discrepancies, toRecover };
}

// ─────────────────────────────── Доставки (сводка) ───────────────────────────────

export interface ShipmentLike {
  status: string;
  tracking_status?: string;
}

export interface ShipmentsSummary {
  total: number;
  delivered: number;
  inTransit: number;
  atCustoms: number;
}

/** Группировка доставок по статусу/трекингу для дашборда (fallback, когда /dashboard недоступен). */
export function summarizeShipments(items: ShipmentLike[]): ShipmentsSummary {
  let delivered = 0;
  let inTransit = 0;
  let atCustoms = 0;
  for (const s of items) {
    if (s.status === "delivered") delivered += 1;
    else if (s.tracking_status === "at_customs") atCustoms += 1;
    else if (s.status !== "planned") inTransit += 1;
  }
  return { total: items.length, delivered, inTransit, atCustoms };
}

// ─────────────────────────────── Парк (допуск транспорта) ───────────────────────────────

export interface VehicleLike {
  capacity_kg: number;
  temp_control: boolean;
}

export interface CargoReq {
  weight_kg: number;
  needs_temp?: boolean;
}

/** Подходит ли ТС под груз: вес ≤ грузоподъёмности и (не нужен холод | есть рефрижератор). */
export function vehicleFits(vehicle: VehicleLike, req: CargoReq): boolean {
  if (req.weight_kg > vehicle.capacity_kg) return false;
  if (req.needs_temp && !vehicle.temp_control) return false;
  return true;
}

// ─────────────────────────────── Статусы тендера ───────────────────────────────

const RFQ_FLOW = ["draft", "sent", "collecting", "negotiation", "awarded", "contracted"] as const;

const RFQ_LABELS: Record<string, string> = {
  draft: "Черновик",
  sent: "Разослан",
  collecting: "Сбор ставок",
  negotiation: "Переговоры",
  awarded: "Победитель выбран",
  contracted: "Законтрактован",
};

/** Следующий статус тендера по цепочке; финал и неизвестные значения остаются на месте. */
export function nextRfqStatus(status: string): string {
  const i = RFQ_FLOW.indexOf(status as (typeof RFQ_FLOW)[number]);
  if (i === -1 || i === RFQ_FLOW.length - 1) return status;
  return RFQ_FLOW[i + 1];
}

/** Русская подпись статуса тендера; неизвестное значение возвращается как есть. */
export function rfqStatusLabel(status: string): string {
  return RFQ_LABELS[status] ?? status;
}

// ─────────────────────────────── Статусы доставки ───────────────────────────────

/** Поток статусов доставки: planned → assigned → in_transit → at_customs → delivered.
 *  at_customs опционален (бекенд эмитит его как tracking_status; основной status может идти
 *  in_transit → delivered напрямую). */
export const DELIVERY_FLOW = [
  "planned",
  "assigned",
  "in_transit",
  "at_customs",
  "delivered",
] as const;

const DELIVERY_LABELS: Record<string, string> = {
  planned: "Запланирована",
  assigned: "Перевозчик назначен",
  in_transit: "В пути",
  at_customs: "На таможне",
  delivered: "Доставлено",
};

/** Разрешённые переходы статуса доставки (форвард по потоку + at_customs↔in_transit).
 *  Назад двигаться запрещено (был доставлен — не «отдоставить»). */
const DELIVERY_TRANSITIONS: Record<string, ReadonlyArray<string>> = {
  planned: ["assigned"],
  assigned: ["in_transit"],
  in_transit: ["at_customs", "delivered"],
  at_customs: ["in_transit", "delivered"],
  delivered: [],
};

/** Допустимые следующие статусы доставки из текущего (пустой массив = тупик). */
export function allowedDeliveryTransitions(status: string): ReadonlyArray<string> {
  return DELIVERY_TRANSITIONS[status] ?? [];
}

/** Можно ли двинуть статус доставки `from → to`? Назад и в неизвестное состояние — нельзя. */
export function canTransitionDelivery(from: string, to: string): boolean {
  return allowedDeliveryTransitions(from).includes(to);
}

/** Русская подпись статуса доставки; неизвестное значение возвращается как есть. */
export function deliveryStatusLabel(status: string): string {
  return DELIVERY_LABELS[status] ?? status;
}

// ─────────────────────────────── Стадии импорта ───────────────────────────────

/** Цепочка импорта (зеркало IMPORT_STAGES бэка). ИНФО-этапы для дашборда. */
export const IMPORT_FLOW = [
  "factory",
  "consolidation",
  "in_transit",
  "customs",
  "warehouse",
] as const;

const IMPORT_LABELS: Record<string, string> = {
  factory: "Фабрика",
  consolidation: "Консолидация",
  in_transit: "В пути",
  customs: "Таможня",
  warehouse: "Приёмка на склад",
};

/** Следующая стадия импорта по цепочке (для кнопки «продвинуть»); финал — на месте. */
export function nextImportStage(stage: string): string {
  const i = IMPORT_FLOW.indexOf(stage as (typeof IMPORT_FLOW)[number]);
  if (i === -1 || i === IMPORT_FLOW.length - 1) return stage;
  return IMPORT_FLOW[i + 1];
}

/** Русская подпись стадии импорта; неизвестное значение возвращается как есть. */
export function importStageLabel(stage: string): string {
  return IMPORT_LABELS[stage] ?? stage;
}

// ─────────────────────────────── Σ видимого фрахта (LOG3-8) ───────────────────────────────

export interface FreightShipment {
  status: string;
  amount: number;
}
export interface FreightImport {
  stage: string;
  amount: number;
}

/** Σ видимого фрахта логистики в BYN: доставки delivered + импорт в warehouse, amount > 0.
 *
 *  Зеркало серверного контракта (LOG3-1 + LOG3-2): ровно эти суммы летят на finance как
 *  ``logistics.freight.cost`` (``leg='domestic'`` при delivered ``Shipment``, ``leg='import'``
 *  при warehouse ``ImportShipment``). Страховка против дрейфа «на экране 1000, в финансах 800». */
export function totalFreightByn(
  domestic: FreightShipment[],
  imports: FreightImport[],
): number {
  let total = 0;
  for (const s of domestic) {
    if (s.status === "delivered" && s.amount > 0) total += s.amount;
  }
  for (const i of imports) {
    if (i.stage === "warehouse" && i.amount > 0) total += i.amount;
  }
  return round2(total);
}
