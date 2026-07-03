// Чистая логика каталога SKU (витрина «Номенклатура»): поиск + фильтр по категории.
// Без зависимостей React/Next — тестируется co-located vitest (см. reference-data.test.ts).

import type { NomenclatureGroup, SkuRow } from "@/lib/reference-data";

/** Строки, у которых code/title содержат подстроку (регистронезависимо). Пусто — все строки. */
export function filterSkusBySearch(rows: SkuRow[], query: string): SkuRow[] {
  const q = query.trim().toLowerCase();
  if (!q) return rows;
  return rows.filter(
    (r) => r.title.toLowerCase().includes(q) || r.code.toLowerCase().includes(q),
  );
}

/** Строки с заданным category_id. `null` — без фильтра (все строки, включая без категории). */
export function filterSkusByCategory(rows: SkuRow[], categoryId: number | null): SkuRow[] {
  if (categoryId === null) return rows;
  return rows.filter((r) => r.category_id === categoryId);
}

/** Карта id → имя категории (для колонки «Категория» в таблице). */
export function categoryNameMap(groups: NomenclatureGroup[]): Map<number, string> {
  return new Map(groups.map((g) => [g.id, g.name]));
}
