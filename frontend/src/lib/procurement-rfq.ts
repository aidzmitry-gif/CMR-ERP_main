// Домен «RFQ / тендер закупки» поверх API выбранного юрлица.
// Запрос цен → предложения поставщиков (цена/срок/incoterms) → выбор победителя (award).
// Бэкенд сортирует предложения по цене и помечает лучшую (best_bid_id) + эмитит rfq.awarded.

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
  number: string;
  organization_id: number;
  request_key: string;
  item: string;
  sku_code: string;
  qty: number;
  request_id: number | null;
  status: string; // open | awarded | cancelled
  due_date: string | null;
  bids: RfqBid[];
  best_bid_id: number | null;
}

export interface RfqPage { organization_id: number; items: Rfq[]; next_after_id: number | null }

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

/** `null` при ошибке — чтобы не затереть SSR-данные пустым списком. */
export async function fetchRfqs(organizationId: number, afterId = 0): Promise<RfqPage | null> {
  try {
    const res = await fetch(`/api/procurement/organizations/${organizationId}/rfq?after_id=${afterId}`, { cache: "no-store" });
    if (!res.ok) return null;
    const page = await res.json() as RfqPage;
    if (page.organization_id !== organizationId || !Array.isArray(page.items) ||
        page.items.some((row) => row.organization_id !== organizationId) ||
        (page.next_after_id !== null && (!Number.isSafeInteger(page.next_after_id) || page.next_after_id <= afterId))) return null;
    return page;
  } catch {
    return null;
  }
}

export async function createRfq(organizationId: number, input: {
  request_key: string;
  request_id: number;
}): Promise<Rfq | null> {
  try {
    const res = await fetch(`/api/procurement/organizations/${organizationId}/rfq`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!res.ok) return null;
    const row = await res.json() as Rfq;
    return row.organization_id === organizationId ? row : null;
  } catch {
    return null;
  }
}

export async function addBid(
  organizationId: number,
  rfqId: number,
  bid: { bid_key: string; supplier_id: number; price_byn: string; lead_time_days?: number | null; incoterms?: string; note?: string },
): Promise<Rfq | null> {
  try {
    const res = await fetch(`/api/procurement/organizations/${organizationId}/rfq/${rfqId}/bids`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bid),
    });
    if (!res.ok) return null;
    const row = await res.json() as Rfq;
    return row.organization_id === organizationId && row.id === rfqId ? row : null;
  } catch {
    return null;
  }
}

export async function awardRfq(organizationId: number, rfqId: number, bidId: number): Promise<Rfq | null> {
  try {
    const res = await fetch(`/api/procurement/organizations/${organizationId}/rfq/${rfqId}/award`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bid_id: bidId }),
    });
    if (!res.ok) return null;
    const row = await res.json() as Rfq;
    return row.organization_id === organizationId && row.id === rfqId ? row : null;
  } catch {
    return null;
  }
}
