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
