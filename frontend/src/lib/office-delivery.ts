// Домен «Офис · доставка и трекинг» — чистая логика поверх отгрузок офис-менеджера.
// Без зависимостей от React/сети: парс веса, гард ≥300 кг (заявка перевозчику),
// классификация стадии трекинга, сводка. Деньги — в BYN (форматирование — в UI через formatByn).

/** Стадии трекинга отгрузки. */
export type TrackingStage = "new" | "packed" | "in_transit" | "delivered" | "delayed";

/** Тон бейджа стадии (совпадает с палитрой FunnelTone в UI). */
export type TrackingTone = "slate" | "violet" | "blue" | "green" | "red";

export interface TrackingMeta {
  label: string;
  tone: TrackingTone;
}

export interface Delivery {
  id: number;
  code: string; // № отгрузки
  company: string;
  /** Вес как введено пользователем: «1 200 кг», «0.5 т», «350» (кг по умолчанию). */
  weight: string;
  /** Сумма отгрузки в BYN. */
  amount: number;
  stage: TrackingStage;
  /** Назначенный перевозчик (если заявка уже оформлена). */
  carrier?: string;
  /** Плановая дата доставки (ETA). */
  eta?: string;
  /** Город назначения. */
  destination?: string;
  /** Сырая стадия документа office (ready/shipped/…) — для живых данных; demo — undefined. */
  officeStage?: string;
}

export interface DeliverySummary {
  total: number;
  inTransit: number;
  delivered: number;
  delayed: number;
  /** Тяжёлые отгрузки (≥300 кг) без назначенного перевозчика — нужна заявка. */
  needCarrierRequest: number;
  /** Суммарные деньги по отгрузкам, BYN. */
  totalAmount: number;
}

/** Порог веса, с которого отгрузка требует оформления заявки перевозчику, кг. */
export const CARRIER_THRESHOLD_KG = 300;

const TRACKING: Record<TrackingStage, TrackingMeta> = {
  new: { label: "Создана", tone: "slate" },
  packed: { label: "Собрана", tone: "violet" },
  in_transit: { label: "В пути", tone: "blue" },
  delivered: { label: "Доставлена", tone: "green" },
  delayed: { label: "Задержка", tone: "red" },
};

/**
 * Парсит вес в килограммы из строки или числа.
 * «350» / «350 кг» → 350; «1 200 кг» → 1200; «1,2 т» / «0.5 т» → 1200 / 500.
 * Тонны (т/t) умножаются на 1000; килограммы (кг/kg) и голое число — как есть.
 * Непарсируемое, пустое или неположительное → 0 (приложение не должно падать).
 */
export function parseWeightKg(raw: string | number): number {
  if (typeof raw === "number") {
    return Number.isFinite(raw) && raw > 0 ? raw : 0;
  }
  if (!raw) return 0;
  // убрать пробелы (вкл. неразрывный) — разделители тысяч; запятую → точку
  const norm = raw.toString().trim().toLowerCase().replace(/[\s ]/g, "").replace(",", ".");
  const match = norm.match(/-?\d+(?:\.\d+)?/);
  if (!match) return 0;
  const value = Number.parseFloat(match[0]);
  if (!Number.isFinite(value) || value <= 0) return 0;
  const isKg = /кг|kg/.test(norm);
  const isTonne = !isKg && /т|t/.test(norm);
  return isTonne ? value * 1000 : value;
}

/** Гард: требуется ли заявка перевозчику (вес ≥ 300 кг). */
export function requiresCarrierRequest(raw: string | number): boolean {
  return parseWeightKg(raw) >= CARRIER_THRESHOLD_KG;
}

/** Метаданные стадии трекинга; неизвестная стадия → фолбэк «Создана» (без падения). */
export function classifyTracking(stage: TrackingStage): TrackingMeta {
  return TRACKING[stage] ?? TRACKING.new;
}

/** Короткий доступ к подписи стадии. */
export function trackingLabel(stage: TrackingStage): string {
  return classifyTracking(stage).label;
}

/** Сводка по списку отгрузок: счётчики стадий, деньги (BYN), сколько ждут заявку перевозчику. */
export function summarizeDeliveries(list: Delivery[]): DeliverySummary {
  return list.reduce<DeliverySummary>(
    (acc, d) => {
      acc.total += 1;
      acc.totalAmount += d.amount ?? 0;
      if (d.stage === "in_transit") acc.inTransit += 1;
      if (d.stage === "delivered") acc.delivered += 1;
      if (d.stage === "delayed") acc.delayed += 1;
      if (requiresCarrierRequest(d.weight) && !d.carrier) acc.needCarrierRequest += 1;
      return acc;
    },
    { total: 0, inTransit: 0, delivered: 0, delayed: 0, needCarrierRequest: 0, totalAmount: 0 },
  );
}

/** Перевозчик из справочника office (GET /office/carriers). */
export interface OfficeCarrier {
  id: string;
  name: string;
  type: string;
  rating: number;
  eta: string;
  price_from: number;
  zone: string;
  heavy: boolean; // берёт тяжёлый груз (≥300 кг)
}

/** Зеркало office/carriers.py — фолбэк модалки, если /office/carriers недоступен. */
export const OFFICE_CARRIERS: OfficeCarrier[] = [
  { id: "cdek", name: "СДЭК", type: "Экспресс-доставка", rating: 4.8, eta: "1–2 дня", price_from: 45, zone: "вся РБ", heavy: false },
  { id: "evropochta", name: "Европочта", type: "Курьер · сеть ПВЗ", rating: 4.6, eta: "1–3 дня", price_from: 28, zone: "вся РБ", heavy: false },
  { id: "belpochta", name: "Белпочта", type: "Посылки · EMS", rating: 4.2, eta: "2–4 дня", price_from: 18, zone: "вся РБ", heavy: false },
  { id: "dellin", name: "Деловые Линии", type: "Сборный груз · LTL", rating: 4.7, eta: "1–2 дня", price_from: 95, zone: "вся РБ", heavy: true },
  { id: "dpd", name: "DPD", type: "Экспресс · палеты", rating: 4.5, eta: "1–2 дня", price_from: 52, zone: "вся РБ", heavy: true },
  { id: "own", name: "Свой транспорт", type: "Тент 5 т · день в день", rating: 4.9, eta: "день в день", price_from: 0, zone: "Минск + область", heavy: true },
];

/**
 * Перевозчики, пригодные под вес отгрузки: тяжёлый груз (≥300 кг) могут везти
 * только перевозчики с флагом `heavy`; лёгкий — любой.
 */
export function eligibleCarriers(carriers: OfficeCarrier[], rawWeight: string | number): OfficeCarrier[] {
  if (!requiresCarrierRequest(rawWeight)) return carriers;
  return carriers.filter((c) => c.heavy);
}

/**
 * Можно ли оформить заявку перевозчику для отгрузки. Заявка валидна только для
 * документа на стадии «Готово к отгрузке» (office stage `ready`); для демо-данных
 * (без `officeStage`) разрешаем — это локальный прототип без backend.
 */
export function canRequestCarrier(d: Delivery): boolean {
  return d.officeStage === undefined || d.officeStage === "ready";
}

// ─────────── Маппинг документа офис-менеджера (API /office/docs) в строку доставки ───────────

/** Документ офис-менеджера из API (подмножество полей для трекинга доставки). */
export interface OfficeDocApi {
  id: number;
  number: string;
  company: string;
  amount: number;
  delivery: string;      // назначенный перевозчик
  docs_status: string;   // текст статуса доставки (пишется логистикой через события)
  stage: string;         // ready/shipped/docs/await_pay/paid
  region?: string;
  weight?: string;
  op_date?: string | null;
}

/**
 * Стадия трекинга из стадии документа и текста статуса доставки.
 * Приоритет — тексту из логистики (`docs_status`: «…В пути…», «Доставлено…»),
 * затем по стадии документа офиса. Неизвестное → «Создана» (без падения).
 */
export function officeStageToTracking(stage: string, docsStatus = ""): TrackingStage {
  const s = (docsStatus || "").toLowerCase();
  if (s.includes("доставлен")) return "delivered";
  if (s.includes("задерж") || s.includes("проблем")) return "delayed";
  if (s.includes("пути") || s.includes("трансп")) return "in_transit";
  if (stage === "paid" || stage === "await_pay" || stage === "docs") return "delivered";
  if (stage === "shipped") return "in_transit";
  return "new";
}

/** Маппинг документа офис-менеджера (API) в строку секции «Доставка». */
export function officeDocToDelivery(doc: OfficeDocApi): Delivery {
  return {
    id: doc.id,
    code: doc.number,
    company: doc.company,
    weight: doc.weight ?? "",
    amount: doc.amount ?? 0,
    stage: officeStageToTracking(doc.stage, doc.docs_status),
    carrier: doc.delivery || undefined,
    destination: doc.region || undefined,
    eta: doc.op_date ?? undefined,
    officeStage: doc.stage,
  };
}

/** Демо-данные: доска работает без backend (фолбэк, если /office/docs недоступен). */
export const DEMO_DELIVERIES: Delivery[] = [
  { id: 1, code: "0156", company: "ООО МеталлПром", weight: "1 200 кг", amount: 184_500, stage: "packed", destination: "Минск", eta: "12.06" },
  { id: 2, code: "0151", company: "ПАО ХимПром", weight: "320 кг", amount: 96_400, stage: "in_transit", carrier: "Деловые Линии", destination: "Гомель", eta: "11.06" },
  { id: 3, code: "0148", company: "ООО АльфаСталь", weight: "85 кг", amount: 21_300, stage: "in_transit", carrier: "СДЭК", destination: "Брест", eta: "11.06" },
  { id: 4, code: "0140", company: "ИП Сидоров", weight: "2,4 т", amount: 312_000, stage: "delayed", destination: "Витебск", eta: "10.06" },
  { id: 5, code: "0133", company: "ООО ТехноСбыт", weight: "540 кг", amount: 73_900, stage: "new", destination: "Могилёв", eta: "13.06" },
  { id: 6, code: "0129", company: "ООО МеталлПром", weight: "60 кг", amount: 18_200, stage: "delivered", carrier: "СДЭК", destination: "Минск", eta: "09.06" },
];
