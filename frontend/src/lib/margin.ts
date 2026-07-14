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

/**
 * Источник себестоимости для АГРЕГАТНОЙ метки сделки: единый источник, только если у всех
 * priced-позиций с известным источником он одинаков; `"mixed"` — если источники разные (тогда
 * нельзя приписывать всей сделке метку одной позиции: себес суммирует разные источники —
 * список даёт честный per-позиционный ярлык, PLATFORM #1); `null` — источников нет.
 */
export function aggregateCostSource(lines: MarginLine[]): CostSource | "mixed" {
  const srcs = new Set(
    lines
      .filter((l) => l.status === "priced" && l.cost_source != null)
      .map((l) => l.cost_source),
  );
  if (srcs.size === 0) return null;
  if (srcs.size === 1) return [...srcs][0] as Exclude<CostSource, null>;
  return "mixed";
}
