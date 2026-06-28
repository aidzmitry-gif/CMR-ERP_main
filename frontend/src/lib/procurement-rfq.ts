// Домен «RFQ / тендер закупки» поверх backend-API `/procurement/rfq`.
// Запрос цен → предложения поставщиков (цена/срок/incoterms) → выбор победителя (award).
// Бэкенд сортирует предложения по цене и помечает лучшую (best_bid_id) + эмитит rfq.awarded.

const BASE = process.env.BACKEND_URL ?? "http://localhost:8000";

export interface RfqBid {
  id: number;
  rfq_id: number;
  supplier_id: number | null;
  price_byn: number;
  lead_time_days: number | null;
  incoterms: string;
  note: string;
  is_winner: boolean;
}

export interface Rfq {
  id: number;
  item: string;
  sku_code: string;
  qty: number;
  request_id: number | null;
  status: string; // open | awarded | cancelled
  due_date: string | null;
  bids: RfqBid[];
  best_bid_id: number | null;
}

const STATUS_LABEL: Record<string, string> = {
  open: "Открыт",
  awarded: "Победитель выбран",
  cancelled: "Отменён",
};

export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

/** id предложения с минимальной ценой (fallback-подсветка, если бэк не прислал best_bid_id). */
export function bestBidId(bids: RfqBid[]): number | null {
  if (!bids.length) return null;
  return bids.reduce((best, b) => (b.price_byn < best.price_byn ? b : best)).id;
}

function roleHeaders(roles?: string): Record<string, string> | undefined {
  return roles ? { "X-User-Roles": roles } : undefined;
}

export async function fetchRfqsServer(roles?: string): Promise<Rfq[]> {
  try {
    const res = await fetch(`${BASE}/procurement/rfq`, { cache: "no-store", headers: roleHeaders(roles) });
    if (!res.ok) return [];
    return (await res.json()) as Rfq[];
  } catch {
    return [];
  }
}

/** `null` при ошибке — чтобы не затереть SSR-данные пустым списком. */
export async function fetchRfqs(): Promise<Rfq[] | null> {
  try {
    const res = await fetch("/api/procurement/rfq", { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as Rfq[];
  } catch {
    return null;
  }
}

export async function createRfq(input: {
  item: string;
  sku_code?: string;
  qty?: number;
}): Promise<Rfq | null> {
  try {
    const res = await fetch("/api/procurement/rfq", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!res.ok) return null;
    return (await res.json()) as Rfq;
  } catch {
    return null;
  }
}

export async function addBid(
  rfqId: number,
  bid: { supplier_id?: number | null; price_byn: number; lead_time_days?: number | null; incoterms?: string; note?: string },
): Promise<Rfq | null> {
  try {
    const res = await fetch(`/api/procurement/rfq/${rfqId}/bids`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bid),
    });
    if (!res.ok) return null;
    return (await res.json()) as Rfq;
  } catch {
    return null;
  }
}

export async function awardRfq(rfqId: number, bidId: number): Promise<Rfq | null> {
  try {
    const res = await fetch(`/api/procurement/rfq/${rfqId}/award`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bid_id: bidId }),
    });
    if (!res.ok) return null;
    return (await res.json()) as Rfq;
  } catch {
    return null;
  }
}
