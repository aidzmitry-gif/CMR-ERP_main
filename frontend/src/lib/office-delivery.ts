// Домен «Офис · доставка и трекинг»: только факты, полученные от документов и
// явных событий доставки. Неизвестные значения остаются неизвестными.

export type TrackingStage = "new" | "packed" | "in_transit" | "delivered" | "delayed" | "unknown";
export type TrackingTone = "slate" | "violet" | "blue" | "green" | "red";

export interface TrackingMeta {
  label: string;
  tone: TrackingTone;
}

export interface Delivery {
  id: number;
  code: string;
  company: string;
  /** Вес как записан в офисном документе; пустое и неразбираемое значение — unknown. */
  weight: string;
  /** Сумма офисного документа, BYN. */
  amount: number;
  stage: TrackingStage;
  /** Исходный текст поля delivery, которое может содержать перевозчика или способ доставки. */
  carrier?: string;
  destination?: string;
  officeStage?: string;
}

export interface DeliverySummary {
  total: number;
  inTransit: number;
  delivered: number;
  delayed: number;
  trackingKnown: number;
  weightKnown: number;
  totalAmount: number;
}

const TRACKING: Record<TrackingStage, TrackingMeta> = {
  new: { label: "Создана", tone: "slate" },
  packed: { label: "Собрана", tone: "violet" },
  in_transit: { label: "В пути", tone: "blue" },
  delivered: { label: "Доставлена", tone: "green" },
  delayed: { label: "Задержка", tone: "red" },
  unknown: { label: "Не подтверждён", tone: "slate" },
};

/** Возвращает вес в кг или null, если документ не содержит проверяемого значения. */
export function parseWeightKg(raw: string | number): number | null {
  if (typeof raw === "number") {
    return Number.isFinite(raw) && raw > 0 ? raw : null;
  }
  if (!raw) return null;
  const norm = raw.toString().trim().toLowerCase().replace(/[\s ]/g, "").replace(",", ".");
  const match = norm.match(/^(\d+(?:\.\d+)?)(kg|кг|t|т)?$/);
  if (!match) return null;
  const value = Number(match[1]);
  if (!Number.isFinite(value) || value <= 0) return null;
  const isTonne = match[2] === "т" || match[2] === "t";
  const valueKg = isTonne ? value * 1000 : value;
  return Number.isFinite(valueKg) ? valueKg : null;
}

export function classifyTracking(stage: TrackingStage): TrackingMeta {
  return TRACKING[stage] ?? TRACKING.unknown;
}

export function trackingLabel(stage: TrackingStage): string {
  return classifyTracking(stage).label;
}

export function summarizeDeliveries(list: Delivery[]): DeliverySummary {
  return list.reduce<DeliverySummary>(
    (acc, delivery) => {
      acc.total += 1;
      acc.totalAmount += delivery.amount;
      if (delivery.stage !== "unknown") acc.trackingKnown += 1;
      if (parseWeightKg(delivery.weight) !== null) acc.weightKnown += 1;
      if (delivery.stage === "in_transit") acc.inTransit += 1;
      if (delivery.stage === "delivered") acc.delivered += 1;
      if (delivery.stage === "delayed") acc.delayed += 1;
      return acc;
    },
    { total: 0, inTransit: 0, delivered: 0, delayed: 0, trackingKnown: 0, weightKnown: 0, totalAmount: 0 },
  );
}

/** Прототипный каталог используется только для выбора имени; коммерческие поля игнорируются. */
export interface OfficeCarrier {
  id: string;
  name: string;
}

export interface OfficeDocApi {
  id: number;
  number: string;
  company: string;
  amount: number;
  delivery: string;
  docs_status: string;
  stage: string;
  region?: string | null;
  weight?: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isOfficeDocList(value: unknown): value is OfficeDocApi[] {
  return (
    Array.isArray(value) &&
    value.every(
      (doc) =>
        isRecord(doc) &&
        Number.isSafeInteger(doc.id) &&
        typeof doc.number === "string" &&
        typeof doc.company === "string" &&
        typeof doc.amount === "number" &&
        Number.isFinite(doc.amount) &&
        typeof doc.delivery === "string" &&
        typeof doc.docs_status === "string" &&
        typeof doc.stage === "string" &&
        (doc.region === undefined || doc.region === null || typeof doc.region === "string") &&
        (doc.weight === undefined || doc.weight === null || typeof doc.weight === "string"),
    )
  );
}

export function isOfficeCarrierList(value: unknown): value is OfficeCarrier[] {
  return (
    Array.isArray(value) &&
    value.every(
      (carrier) =>
        isRecord(carrier) && typeof carrier.id === "string" && typeof carrier.name === "string",
    )
  );
}

/** Только стадия ready разрешает показать отправку заявки; неизвестная стадия не подразумевает ready. */
export function canRequestCarrier(delivery: Delivery): boolean {
  return delivery.officeStage === "ready";
}

/** Документ API содержит трекинг только когда это явно записано событием доставки. */
export function officeStageToTracking(_stage: string, docsStatus = ""): TrackingStage {
  const status = docsStatus.trim().toLowerCase();
  if (status === "доставлено, закрываем документы") return "delivered";

  const trackingStatus = status.match(/^доставка:\s*(.+)$/)?.[1]?.trim();
  if (!trackingStatus) return "unknown";
  if (/^(?:доставлен(?:а|о|ы)?|доставлено, закрываем документы)$/.test(trackingStatus)) return "delivered";
  if (/^(?:задержка(?: маршрута)?|задержан(?:а|о|ы)?|проблема(?: с доставкой)?)$/.test(trackingStatus)) return "delayed";
  if (/^(?:в пути(?:\s*·\s*.+)?|в транзите|транспортируется)$/.test(trackingStatus)) return "in_transit";
  return "unknown";
}

export function officeDocToDelivery(doc: OfficeDocApi): Delivery {
  return {
    id: doc.id,
    code: doc.number,
    company: doc.company,
    weight: doc.weight ?? "",
    amount: doc.amount,
    stage: officeStageToTracking(doc.stage, doc.docs_status),
    carrier: doc.delivery || undefined,
    destination: doc.region || undefined,
    officeStage: doc.stage,
  };
}
