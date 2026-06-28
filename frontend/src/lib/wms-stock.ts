// Домен «Остатки (зеркало 1С)» поверх backend-API `/wms/stock`.
// Истина остатка — 1С/integrations; склад только читает через шлюз (read-only).
// Чистые функции (фильтр/группировка/итоги) тестируются без React; SSR-загрузка
// ходит на BACKEND_URL, клиентское обновление — через прокси `/api`.

const BASE = process.env.BACKEND_URL ?? "http://localhost:8000";

export interface StockMirrorRow {
  sku_code: string;
  title: string;
  unit: string;
  warehouse: string;
  qty_available: number; // всего на складе
  qty_reserved: number; // из них зарезервировано
  qty_free: number; // свободно к продаже = available − reserved (≥0)
  qty_forecast: number; // ожидается (в пути / прогноз прихода)
  updated_at: string | null;
}

export interface StockMirror {
  rows: StockMirrorRow[];
  warehouses: string[];
  total_available: number;
  total_reserved: number;
  total_free: number;
  sku_count: number;
  gateway: boolean; // шлюз остатков подключён; false → источник 1С/integrations недоступен
  truncated: boolean; // упёрлись в limit — есть ещё SKU за страницей
}

const EMPTY: StockMirror = {
  rows: [],
  warehouses: [],
  total_available: 0,
  total_reserved: 0,
  total_free: 0,
  sku_count: 0,
  gateway: false,
  truncated: false,
};

/** Фильтр строк по складу (""/«все» — без фильтра). Чистая функция для UI/тестов. */
export function filterByWarehouse(rows: StockMirrorRow[], warehouse: string): StockMirrorRow[] {
  return warehouse ? rows.filter((r) => r.warehouse === warehouse) : rows;
}

/** Фильтр строк по подстроке в коде/названии SKU (регистронезависимо). */
export function filterByQuery(rows: StockMirrorRow[], q: string): StockMirrorRow[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return rows;
  return rows.filter(
    (r) => r.sku_code.toLowerCase().includes(needle) || r.title.toLowerCase().includes(needle),
  );
}

export interface StockTotals {
  available: number;
  reserved: number;
  free: number;
  skuCount: number;
}

/** Итоги по набору строк (для KPI-плашек): сумма наличия/резерва/свободного + число SKU. */
export function stockTotals(rows: StockMirrorRow[]): StockTotals {
  return {
    available: rows.reduce((s, r) => s + r.qty_available, 0),
    reserved: rows.reduce((s, r) => s + r.qty_reserved, 0),
    free: rows.reduce((s, r) => s + r.qty_free, 0),
    skuCount: new Set(rows.map((r) => r.sku_code)).size,
  };
}

function roleHeaders(roles?: string): Record<string, string> | undefined {
  return roles ? { "X-User-Roles": roles } : undefined;
}

/** Остатки-зеркало для SSR (server component); при недоступности бэка — пусто (gateway=false). */
export async function fetchStockMirrorServer(roles?: string): Promise<StockMirror> {
  try {
    const res = await fetch(`${BASE}/wms/stock`, { cache: "no-store", headers: roleHeaders(roles) });
    if (!res.ok) return EMPTY;
    return (await res.json()) as StockMirror;
  } catch {
    return EMPTY;
  }
}

/** Остатки-зеркало (клиент, через прокси /api) — для тихого перечитывания. */
export async function fetchStockMirror(): Promise<StockMirror> {
  try {
    const res = await fetch("/api/wms/stock", { cache: "no-store" });
    if (!res.ok) return EMPTY;
    return (await res.json()) as StockMirror;
  } catch {
    return EMPTY;
  }
}
