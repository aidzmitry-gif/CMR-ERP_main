// Домен «Открытые заказы поставщикам (в пути)» поверх backend-API `/procurement/open-orders`.
// Открытый заказ (ordered/shipped/customs) = товар ещё не принят → sales вычитает его в
// нетто-доступности. Чистые функции (статус/ETA/итоги) тестируются без React; SSR-загрузка
// ходит на BACKEND_URL, клиентское обновление — через прокси `/api`.

const BASE = process.env.BACKEND_URL ?? "http://localhost:8000";

export interface OpenOrderLine {
  sku_code: string;
  qty: number;
  goods_value_byn: number;
  weight: number;
  volume: number;
}

export interface OpenOrder {
  id: number;
  number: string;
  supplier: string;
  status: string; // ordered | shipped | customs
  eta_date: string | null;
  freight_byn: number;
  lines: OpenOrderLine[];
}

const STATUS_LABEL: Record<string, string> = {
  ordered: "Заказан",
  shipped: "Отгружен",
  customs: "Таможня",
};

/** Человекочитаемый статус заказа (неизвестный — как есть). */
export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

/** Дней до ETA (отрицательное = просрочено, 0 = сегодня); null — даты нет/битая. */
export function daysToEta(eta: string | null, now: number = Date.now()): number | null {
  if (!eta) return null;
  const t = Date.parse(eta);
  if (Number.isNaN(t)) return null;
  return Math.ceil((t - now) / 86_400_000);
}

export interface OrderTotals {
  orders: number;
  positions: number; // суммарно позиций по всем заказам
  goods: number; // стоимость товара в пути, BYN
  freight: number; // фрахт в пути, BYN
}

/** Итоги по набору открытых заказов (для KPI-плашек). */
export function orderTotals(orders: OpenOrder[]): OrderTotals {
  return {
    orders: orders.length,
    positions: orders.reduce((s, o) => s + o.lines.length, 0),
    goods: orders.reduce((s, o) => s + o.lines.reduce((g, l) => g + l.goods_value_byn, 0), 0),
    freight: orders.reduce((s, o) => s + o.freight_byn, 0),
  };
}

function roleHeaders(roles?: string): Record<string, string> | undefined {
  return roles ? { "X-User-Roles": roles } : undefined;
}

/** Открытые заказы для SSR (server component); при недоступности бэка — пусто. */
export async function fetchOpenOrdersServer(roles?: string): Promise<OpenOrder[]> {
  try {
    const res = await fetch(`${BASE}/procurement/open-orders`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) return [];
    return (await res.json()) as OpenOrder[];
  } catch {
    return [];
  }
}

/** Открытые заказы (клиент, через прокси /api) — для тихого перечитывания. */
export async function fetchOpenOrders(): Promise<OpenOrder[]> {
  try {
    const res = await fetch("/api/procurement/open-orders", { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as OpenOrder[];
  } catch {
    return [];
  }
}
