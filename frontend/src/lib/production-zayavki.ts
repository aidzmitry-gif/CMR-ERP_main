// Домен «Заявки на сборку» производства — реестр-представление над уже живыми нарядами
// `/production/orders` (+ `/norms` для привязки нормы, `/boms` для обеспеченности).
// НОВОГО backend нет: заявка = наряд (ProductionOrder) в ранних этапах.
// Чистые функции тестируются без React; SSR — на BACKEND_URL, мутации — через прокси `/api`.

import { type Bom, fetchBomsServer } from "@/lib/production-bom";
import { fetchNormsServer, formatNh, type Norm } from "@/lib/production-norms";

const BASE = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export { formatNh, fetchBomsServer, fetchNormsServer };
export type { Bom, Norm };

export type Stage = "queue" | "picking" | "assembly" | "qc" | "packing" | "done";

export interface Order {
  id: number;
  number: string;
  product: string;
  qty: number;
  progress: number;
  priority: string;
  owner: string;
  stage: string; // один из Stage; бэк не валидирует — допускаем любую строку
  due_date: string | null;
  insight: string;
  nh_per_unit: number;
  made_qty: number;
}

export interface OrderInput {
  product: string;
  qty?: number;
  priority?: string;
  owner?: string;
  due_date?: string;
}

const STAGE_LABELS: Record<Stage, string> = {
  queue: "Новая · очередь",
  picking: "Комплектация",
  assembly: "В работе",
  qc: "ОТК",
  packing: "Упаковка",
  done: "Готово",
};

const STAGE_TONES: Record<Stage, string> = {
  queue: "bg-slate-100 text-slate-500",
  picking: "bg-blue-50 text-blue-600",
  assembly: "bg-amber-50 text-amber-600",
  qc: "bg-violet-50 text-violet-600",
  packing: "bg-cyan-50 text-cyan-600",
  done: "bg-green-50 text-green-600",
};

/** Сегменты фильтра по этапу (порядок производственного потока). */
export const STAGES: { id: Stage; label: string }[] = (
  ["queue", "picking", "assembly", "qc", "packing", "done"] as Stage[]
).map((id) => ({ id, label: STAGE_LABELS[id] }));

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage as Stage] ?? stage;
}

export function stageTone(stage: string): string {
  return STAGE_TONES[stage as Stage] ?? "bg-slate-100 text-slate-500";
}

/** Утверждённая норма по точному названию изделия (как на бэке) или null. */
export function normForProduct(norms: Norm[], product: string): Norm | null {
  return norms.find((n) => n.status === "approved" && n.title === product) ?? null;
}

/** Обеспеченность % из BOM по точному названию изделия или null (спецификации нет). */
export function coverageForProduct(boms: Bom[], product: string): number | null {
  const bom = boms.find((b) => b.product === product);
  return bom ? bom.coverage : null;
}

/** Суммарные нормо-часы заявки: норма/шт × количество. */
export function nhTotal(order: Pick<Order, "nh_per_unit" | "qty">): number {
  return order.nh_per_unit * order.qty;
}

export interface ZayavkiCounts {
  total: number;
  withoutNorm: number; // нет утверждённой нормы по изделию
  withoutBom: number; // нет спецификации по изделию
  inProgress: number; // в работе (не очередь и не готово)
}

export function zayavkiCounts(orders: Order[], norms: Norm[], boms: Bom[]): ZayavkiCounts {
  return {
    total: orders.length,
    withoutNorm: orders.filter((o) => normForProduct(norms, o.product) == null).length,
    withoutBom: orders.filter((o) => coverageForProduct(boms, o.product) == null).length,
    inProgress: orders.filter((o) => o.stage !== "queue" && o.stage !== "done").length,
  };
}

// ===== API =====

function roleHeaders(roles?: string): Record<string, string> | undefined {
  return roles ? { "X-User-Roles": roles } : undefined;
}

/** Наряды-заявки для SSR (server component); при недоступности бэка — пусто. */
export async function fetchOrdersServer(roles?: string): Promise<Order[]> {
  try {
    const res = await fetch(`${BASE}/production/orders`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) return [];
    return (await res.json()) as Order[];
  } catch {
    return [];
  }
}

/** Наряды-заявки (клиент, через прокси /api). */
export async function fetchOrders(): Promise<Order[]> {
  try {
    const res = await fetch("/api/production/orders", { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as Order[];
  } catch {
    return [];
  }
}

export async function createOrder(input: OrderInput): Promise<Order | null> {
  try {
    const res = await fetch("/api/production/orders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!res.ok) return null;
    return (await res.json()) as Order;
  } catch {
    return null;
  }
}

/** Сменить этап наряда («Запустить в работу» = queue→assembly). false — отказ бэка. */
export async function updateOrderStage(id: number, stage: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/production/orders/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage }),
    });
    return res.ok;
  } catch {
    return false;
  }
}
