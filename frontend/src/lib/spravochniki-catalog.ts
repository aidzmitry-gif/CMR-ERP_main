// Чистая логика вкладки «Справочники — каталог»: сортировка дерева отделов + дефолт.
// Без зависимостей React/Next — тестируется co-located vitest.

import type { ReferenceCatalog, ReferenceMeta } from "@/lib/reference-data";

// Canonical display order matching the preview HTML tree.
const DEPT_ORDER = [
  "Система",
  "Общие",
  "Продажи",
  "Склад",
  "Финансы",
  "Закупки",
  "Производство",
  "HR",
  "Логистика",
  "Сервис",
  "Маркетинг",
];

export const DEPT_ICONS: Record<string, string> = {
  Система: "⚙️",
  Общие: "🏛",
  Продажи: "📈",
  Склад: "📦",
  Финансы: "💰",
  Закупки: "🛒",
  Производство: "🏭",
  HR: "👥",
  Логистика: "🚚",
  Сервис: "🛠",
  Маркетинг: "📣",
};

export interface DeptGroup {
  dept: string;
  icon: string;
  refs: ReferenceMeta[];
}

/** Departments sorted in canonical order; unknown depts append at the end (alpha). */
export function sortedDepartments(catalog: ReferenceCatalog): DeptGroup[] {
  return Object.entries(catalog.departments)
    .sort(([a], [b]) => {
      const ia = DEPT_ORDER.indexOf(a);
      const ib = DEPT_ORDER.indexOf(b);
      if (ia === -1 && ib === -1) return a.localeCompare(b, "ru");
      if (ia === -1) return 1;
      if (ib === -1) return -1;
      return ia - ib;
    })
    .map(([dept, refs]) => ({ dept, icon: DEPT_ICONS[dept] ?? "📋", refs }));
}

/** First ref of the first department, or null if the catalog is empty. */
export function defaultRef(catalog: ReferenceCatalog): ReferenceMeta | null {
  const groups = sortedDepartments(catalog);
  return groups[0]?.refs[0] ?? null;
}

/**
 * Откуда каталог берёт строки таблицы для справочника. Три источника:
 *
 * - `crud` — generic-роутер под `/system/refs/…` (units/currencies/страны/банки/
 *   курсы/НДС/группы): GET по `endpoint`, полный список.
 * - `query-list` — master-data, которую `reference.query` отдаёт списком
 *   (номенклатура `core.skus`): POST reference.query по ключу.
 * - `lookup-only` — master-data, которую backend НЕ вываливает списком намеренно
 *   (контрагентов/контактов/сотрудников могут быть тысячи; `reference.query`
 *   требует точечный key/name). В каталоге показываем пояснение, а не пустую
 *   таблицу: данные у владельца, точечный доступ — через карточку/AI.
 */
export type RowsSource = "crud" | "query-list" | "lookup-only";

const LOOKUP_ONLY_KEYS = new Set(["core.counterparties", "core.contacts", "core.employees"]);

export function rowsSource(ref: Pick<ReferenceMeta, "endpoint" | "key">): RowsSource {
  if (ref.endpoint.startsWith("/system/refs/")) return "crud";
  if (LOOKUP_ONLY_KEYS.has(ref.key)) return "lookup-only";
  return "query-list";
}
