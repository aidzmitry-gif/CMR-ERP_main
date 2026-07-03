// Домен «Редактор состава заказа (машины)» поверх backend-API `/procurement/orders/{id}`.
// Позиции (sku/qty/стоимость/вес/объём) + фрахт партии; live-распределение landed cost
// считает БЭКЕНД (`/landed-preview`, тот же движок, что на приёмке) — фронт не считает сам.

const BASE = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export interface MachineLine {
  id: number;
  sku_code: string;
  qty: number;
  goods_value_byn: number;
  weight: number;
  volume: number;
}

export interface MachineOrder {
  id: number;
  number: string;
  supplier: string;
  supplier_id: number | null;
  status: string;
  eta_date: string | null;
  freight_byn: number;
  lines: MachineLine[];
}

export interface LandedPreviewLine {
  sku_code: string;
  goods_byn: number;
  allocated_byn: number;
  landed_total_byn: number;
  unit_landed_cost_byn: number;
}

export interface LandedPreview {
  order_id: number;
  freight_byn: number;
  lines: LandedPreviewLine[];
  total_goods_byn: number;
  total_landed_byn: number;
}

export interface NewLine {
  sku_code: string;
  qty: number;
  goods_value_byn: number;
  weight: number;
  volume: number;
}

export function emptyLine(): NewLine {
  return { sku_code: "", qty: 1, goods_value_byn: 0, weight: 0, volume: 0 };
}

function roleHeaders(roles?: string): Record<string, string> | undefined {
  return roles ? { "X-User-Roles": roles } : undefined;
}

/** Заказ с позициями для SSR; null — не найден/бэк недоступен. */
export async function fetchOrderServer(id: number, roles?: string): Promise<MachineOrder | null> {
  try {
    const res = await fetch(`${BASE}/procurement/orders/${id}`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) return null;
    return (await res.json()) as MachineOrder;
  } catch {
    return null;
  }
}

export async function fetchOrder(id: number): Promise<MachineOrder | null> {
  try {
    const res = await fetch(`/api/procurement/orders/${id}`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as MachineOrder;
  } catch {
    return null;
  }
}

/** Предпросмотр распределения landed cost (live-пересчёт) — считает бэкенд. */
export async function fetchLandedPreview(id: number): Promise<LandedPreview | null> {
  try {
    const res = await fetch(`/api/procurement/orders/${id}/landed-preview`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as LandedPreview;
  } catch {
    return null;
  }
}

export async function addLine(id: number, line: NewLine): Promise<MachineOrder | null> {
  try {
    const res = await fetch(`/api/procurement/orders/${id}/lines`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(line),
    });
    if (!res.ok) return null;
    return (await res.json()) as MachineOrder;
  } catch {
    return null;
  }
}

export async function deleteLine(id: number, lineId: number): Promise<MachineOrder | null> {
  try {
    const res = await fetch(`/api/procurement/orders/${id}/lines/${lineId}`, { method: "DELETE" });
    if (!res.ok) return null;
    return (await res.json()) as MachineOrder;
  } catch {
    return null;
  }
}

export async function updateFreight(id: number, freightByn: number): Promise<MachineOrder | null> {
  try {
    const res = await fetch(`/api/procurement/orders/${id}/header`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ freight_byn: freightByn }),
    });
    if (!res.ok) return null;
    return (await res.json()) as MachineOrder;
  } catch {
    return null;
  }
}
