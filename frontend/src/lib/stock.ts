import type { StockRow } from "@/lib/api";

/**
 * Чистая доменная логика подбора товара: агрегация остатков 1С по складам, срок поставки,
 * маржа позиции. Живёт в src/lib (конвенция frontend/CLAUDE.md — доменная логика вне React,
 * тестируется отдельно: stock.test.ts). UI-обёртка — components/kanban/product-picker.tsx.
 */

/** Агрегированный остаток SKU по всем складам. */
export interface SkuStock {
  price: number;
  cost: number | null; // себестоимость из 1С — для маржи «в наличии»
  free: number; // ATP = Σ(available − reserved), не ниже 0
  forecast: number; // «в пути» (приход)
  warehouses: { name: string; free: number; forecast: number }[];
}

/** Свернуть строки /1c/stock в карту sku_code → агрегат (несколько складов на SKU). */
export function aggregateStock(rows: StockRow[]): Record<string, SkuStock> {
  const map: Record<string, SkuStock> = {};
  for (const r of rows) {
    const free = Math.max(0, (r.qty_available || 0) - (r.qty_reserved || 0));
    const m = (map[r.sku_code] ??= { price: 0, cost: null, free: 0, forecast: 0, warehouses: [] });
    m.free += free;
    m.forecast += r.qty_forecast || 0;
    if (!m.price && r.price) m.price = r.price; // цена едина по складам
    if (m.cost == null && r.cost != null) m.cost = r.cost; // себес едина по складам
    if (free > 0 || r.qty_forecast > 0)
      m.warehouses.push({ name: r.warehouse, free, forecast: r.qty_forecast || 0 });
  }
  return map;
}

/** Срок поставки из остатка: свободное → в наличии; только в пути → в пути; иначе под заказ. */
export function srokOf(s?: SkuStock): { label: string; cls: string } {
  if (!s || (s.free === 0 && s.forecast === 0)) return { label: "под заказ", cls: "text-faint" };
  if (s.free > 0) return { label: "в наличии", cls: "text-money" };
  return { label: "в пути", cls: "text-amber-600" };
}

/** Маржа позиции «в наличии» из 1С: (цена − себес)/цена. null — нет себес/цены. */
export function marginOf(s?: SkuStock): { pct: number; gp: number } | null {
  if (!s || !s.price || s.cost == null) return null;
  const gp = s.price - s.cost;
  return { pct: (gp / s.price) * 100, gp };
}
