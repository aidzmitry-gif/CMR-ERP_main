/**
 * Маржа сделки — единый источник для карточки (DealMetrics) и списка позиций (DealItems).
 * Оба потребителя берут себес/цену/маржу из ОДНОГО эндпоинта `/sales/deals/{id}/margin`
 * (фасад ядра price_cost→landed, PC1-4), чтобы цифры и метки провенанса не разъезжались
 * между блоками одного экрана. Типы отражают серверную схему MarginLine/DealMargin.
 */

// Провенанс источника (PC3-4): откуда себес/цена.
export type CostSource = "onec" | "demo" | "landed" | null;
export type PriceSource = "quote" | "onec" | "demo" | null;
export type MarginLineStatus = "priced" | "no_price" | "no_cost";

export interface MarginLine {
  sku_code: string;
  title: string;
  qty: number;
  unit_price: number | null;
  revenue: number | null;
  unit_landed_cost: number | null;
  cogs: number | null;
  margin_pct: number | null;
  status: MarginLineStatus;
  cost_shipment_id: number | null;
  cost_fixed_at: string | null;
  cost_fx_rate: number | null;
  cost_source: CostSource;
  price_source: PriceSource;
}

export interface DealMargin {
  deal_id: number;
  revenue: number;
  cogs_landed: number | null;
  gross_profit: number | null;
  margin_pct: number | null;
  priced_count: number;
  total_count: number;
  reason: string | null;
  lines: MarginLine[];
}

/** Метка источника себестоимости — честная, простыми словами (без жаргона). */
export const COST_SRC_LABEL: Record<Exclude<CostSource, null>, string> = {
  onec: "из 1С",
  demo: "демо (не 1С)",
  landed: "из закупок",
};

/**
 * Фетч маржи сделки (через прокси /api). Возвращает null при ошибке/недоступности —
 * потребитель деградирует честно (не показывает выдуманных денег). Карточка метрик держит
 * свой фетч с состояниями loading/error; списку позиций достаточно null.
 */
export async function fetchDealMargin(dealId: string): Promise<DealMargin | null> {
  try {
    const res = await fetch(`/api/sales/deals/${encodeURIComponent(dealId)}/margin`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as DealMargin;
  } catch {
    return null;
  }
}

/** Индекс строк маржи по коду SKU — для сопоставления с позициями сделки. */
export function marginBySku(margin: DealMargin | null): Map<string, MarginLine> {
  return new Map((margin?.lines ?? []).map((l) => [l.sku_code, l]));
}
