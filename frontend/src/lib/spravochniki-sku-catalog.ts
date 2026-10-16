// Чистая логика каталога SKU (витрина «Номенклатура»): поиск + фильтр по категории.
// Без зависимостей React/Next — тестируется co-located vitest (см. reference-data.test.ts).

import type { NomenclatureGroup, SkuRow } from "@/lib/reference-data";

/** Строки, у которых code/title содержат подстроку (регистронезависимо). Пусто — все строки. */
export function filterSkusBySearch(rows: SkuRow[], query: string): SkuRow[] {
  const words = query.trim().toLocaleLowerCase("ru").split(/\s+/).filter(Boolean);
  if (!words.length) return rows;
  return rows.filter(
    (r) => words.every(word => `${r.code} ${r.title}`.toLocaleLowerCase("ru").includes(word)),
  );
}

/** Строки с заданным category_id. `null` — без фильтра (все строки, включая без категории). */
export function filterSkusByCategory(rows: SkuRow[], categoryId: number | null, groups: NomenclatureGroup[] = []): SkuRow[] {
  if (categoryId === null) return rows;
  const ids = new Set([categoryId]);
  const queue = [categoryId];
  while (queue.length) {
    const parent = queue.pop();
    for (const group of groups) if (group.parent_id === parent && !ids.has(group.id)) {
      ids.add(group.id); queue.push(group.id);
    }
  }
  return rows.filter((r) => r.category_id !== null && ids.has(r.category_id));
}

/** Карта id → имя категории (для колонки «Категория» в таблице). */
export function categoryNameMap(groups: NomenclatureGroup[]): Map<number, string> {
  return new Map(groups.map((g) => [g.id, g.name]));
}
