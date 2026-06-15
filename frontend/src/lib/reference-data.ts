// API-клиент вкладки «Справочники» (registry-витрина поверх backend ядра).
//
// Реестр отдаёт МЕТАДАННЫЕ справочников (что есть, у кого данные, какие колонки/права),
// а сами строки берутся у владельца по его endpoint. Один каталог обслуживает три цели:
// UI-дерево вкладки, RBAC (`permissions`) и каталог для AI (`ai_exposed`).
//
// Конвенции — как в `api.ts`:
//  • SSR-чтения (серверный компонент) ходят на ${BASE} напрямую и пробрасывают роль
//    заголовком (роль читает `role-server.ts` из cookie);
//  • клиентские мутации/интерактив идут через прокси `/api/*` (роль добавит прокси);
//  • любой фетч обёрнут try/catch с безопасным fallback (бэк недоступен → пусто/null),
//    чтобы прототип-вкладка не падала, а деградировала на демо.
//
// Чистая доменная логика (мапперы/хелперы ниже) — без зависимостей React/Next,
// тестируется отдельно (`reference-data.test.ts`).

// Базовый URL бэкенда для SSR-фетчей (как в api.ts).
const BASE = process.env.BACKEND_URL ?? "http://localhost:8000";

function roleHeaders(roles?: string): Record<string, string> | undefined {
  return roles ? { "X-User-Roles": roles } : undefined;
}

// ── Типы каталога (GET /system/references) ───────────────────────────────────

/** Колонка справочника в метаданных каталога. */
export interface ReferenceColumn {
  name: string;
  label: string;
  type: string; // string | number | date | bool | ...
  label_i18n?: Record<string, string> | null;
  editable: boolean;
  semantic: string; // подсказка смысла для AI (напр. "currency.code")
}

/** Метаданные одного справочника (владелец данных — `owner_schema`/`endpoint`). */
export interface ReferenceMeta {
  key: string; // напр. "core.currency_rates"
  title: string;
  module: string; // кто зарегистрировал (core / sales / ...)
  endpoint: string; // где лежат строки у владельца
  owner_schema: string; // схема-владелец (public / sales / ...)
  columns: ReferenceColumn[];
  permissions: string[];
  archivable: boolean;
  versioned: boolean; // историчность SCD2 (курсы/НДС/...)
  ai_exposed: boolean;
  description: string;
}

/** Каталог справочников, сгруппированный по отделам (дерево вкладки). */
export interface ReferenceCatalog {
  departments: Record<string, ReferenceMeta[]>;
}

/** Каталог справочников (SSR): дерево вкладки + метаданные таблиц. */
export async function fetchReferenceCatalog(roles?: string): Promise<ReferenceCatalog> {
  try {
    const res = await fetch(`${BASE}/system/references`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) throw new Error(String(res.status));
    return (await res.json()) as ReferenceCatalog;
  } catch {
    return { departments: {} };
  }
}

// ── Каталог для AI (GET /system/references/ai-catalog) ────────────────────────

export interface AiReference {
  key: string;
  title: string;
  endpoint: string;
  owner_schema: string;
  versioned: boolean;
  columns: { name: string; type: string; semantic: string }[];
  description: string;
}

export interface AiCatalog {
  tool: { name: string; endpoint: string; params: string[]; note: string };
  references: AiReference[];
}

/** Узкий каталог только ai_exposed: чем «представляется» AI-экран (SSR). */
export async function fetchAiCatalog(roles?: string): Promise<AiCatalog | null> {
  try {
    const res = await fetch(`${BASE}/system/references/ai-catalog`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) throw new Error(String(res.status));
    return (await res.json()) as AiCatalog;
  } catch {
    return null;
  }
}

/** Параметры структурного запроса AI (tool reference.query). */
export interface ReferenceQueryInput {
  ref: string;
  key?: string;
  as_of?: string; // YYYY-MM-DD
  name?: string;
  limit?: number;
}

/** Ответ reference.query: result зависит от ref (запись | список | null) — сужает экран. */
export interface ReferenceQueryResult {
  ref: string;
  key?: string;
  as_of?: string | null;
  result: unknown;
}

/** Выполнить структурный запрос AI к справочнику (клиент, интерактивный AI-экран). */
export async function runReferenceQuery(
  input: ReferenceQueryInput,
): Promise<ReferenceQueryResult | null> {
  try {
    const res = await fetch("/api/system/references/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!res.ok) return null;
    return (await res.json()) as ReferenceQueryResult;
  } catch {
    return null;
  }
}

// ── Строки простого справочника (GET/POST/PATCH/DELETE /system/refs/<table>) ──

/** Строка простого справочника. Общие поля + swift у банков. */
export interface SimpleRefRow {
  code: string;
  title: string;
  is_active: boolean;
  swift?: string;
}

/** Имя таблицы простого справочника под /system/refs/*. */
export type SimpleRefTable = "units" | "currencies" | "countries" | "banks";

/** Строки простого справочника (SSR), `archived` — включая архивные. */
export async function fetchSimpleRef(
  table: SimpleRefTable,
  opts: { archived?: boolean; roles?: string } = {},
): Promise<SimpleRefRow[]> {
  try {
    const q = opts.archived ? "?archived=true" : "";
    const res = await fetch(`${BASE}/system/refs/${table}${q}`, {
      cache: "no-store",
      headers: roleHeaders(opts.roles),
    });
    if (!res.ok) throw new Error(String(res.status));
    return (await res.json()) as SimpleRefRow[];
  } catch {
    return [];
  }
}

/** Строки справочника по его endpoint из каталога (SSR), generic — для дерева вкладки.
 * Возвращает «как есть»: экран рендерит по `columns` из метаданных. Не-200 → пусто. */
export async function fetchRefRowsByEndpoint(
  endpoint: string,
  roles?: string,
): Promise<Record<string, unknown>[]> {
  try {
    const res = await fetch(`${BASE}${endpoint}`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) throw new Error(String(res.status));
    const data = await res.json();
    return Array.isArray(data) ? (data as Record<string, unknown>[]) : [];
  } catch {
    return [];
  }
}

/** Создать запись простого справочника (клиент). */
export async function createSimpleRef(
  table: SimpleRefTable,
  row: Partial<SimpleRefRow>,
): Promise<boolean> {
  try {
    const res = await fetch(`/api/system/refs/${table}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(row),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Изменить запись простого справочника по коду (клиент). */
export async function patchSimpleRef(
  table: SimpleRefTable,
  code: string,
  fields: Partial<SimpleRefRow>,
): Promise<boolean> {
  try {
    const res = await fetch(`/api/system/refs/${table}/${encodeURIComponent(code)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Архивировать (мягко удалить) запись простого справочника по коду (клиент). */
export async function archiveSimpleRef(table: SimpleRefTable, code: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/system/refs/${table}/${encodeURIComponent(code)}`, {
      method: "DELETE",
    });
    return res.ok;
  } catch {
    return false;
  }
}

// ── Версионные справочники SCD2 (курсы валют / НДС) ───────────────────────────

/** Версия (полуоткрытый интервал [start_date, end_date); end_date=null → текущая). */
export interface CurrencyRateRow {
  id: number;
  currency_code: string;
  rate: number;
  start_date: string;
  end_date: string | null;
}

export interface VatRateRow {
  id: number;
  code: string;
  title: string;
  rate: number;
  start_date: string;
  end_date: string | null;
}

/** Все версии курсов (SSR); `key` — фильтр по валюте (currency_code). */
export async function fetchCurrencyRates(
  key?: string,
  roles?: string,
): Promise<CurrencyRateRow[]> {
  try {
    const q = key ? `?key=${encodeURIComponent(key)}` : "";
    const res = await fetch(`${BASE}/system/refs/currency-rates${q}`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) throw new Error(String(res.status));
    return (await res.json()) as CurrencyRateRow[];
  } catch {
    return [];
  }
}

/** Все версии ставок НДС (SSR); `key` — фильтр по коду. */
export async function fetchVatRates(key?: string, roles?: string): Promise<VatRateRow[]> {
  try {
    const q = key ? `?key=${encodeURIComponent(key)}` : "";
    const res = await fetch(`${BASE}/system/refs/vat-rates${q}`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) throw new Error(String(res.status));
    return (await res.json()) as VatRateRow[];
  } catch {
    return [];
  }
}

/** Курс валюты, действовавший на дату `on` (предпросмотр SCD2, клиент). */
export async function currencyRateAsOf(
  key: string,
  on: string,
): Promise<CurrencyRateRow | null> {
  try {
    const res = await fetch(
      `/api/system/refs/currency-rates/as-of?key=${encodeURIComponent(key)}&on=${encodeURIComponent(on)}`,
      { cache: "no-store" },
    );
    if (!res.ok) return null;
    return (await res.json()) as CurrencyRateRow;
  } catch {
    return null;
  }
}

/** Добавить новую версию курса с даты (закрывает предыдущую). `table` — currency-rates/vat-rates. */
export async function addRateVersion(
  table: "currency-rates" | "vat-rates",
  payload: Record<string, unknown>,
): Promise<boolean> {
  try {
    const res = await fetch(`/api/system/refs/${table}/versions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return res.ok;
  } catch {
    return false;
  }
}

// ── MDM: дедуп / merge / unmerge (golden record) ─────────────────────────────

export interface DuplicateMember {
  id: number;
  name: string;
}

/** Кластер дублей контрагентов по одинаковому УНП — кандидаты на слияние. */
export interface DuplicateCluster {
  unp: string;
  members: DuplicateMember[];
}

/** Кластеры дублей контрагентов (SSR) — экран дедупликации/MDM. */
export async function fetchDuplicateClusters(roles?: string): Promise<DuplicateCluster[]> {
  try {
    const res = await fetch(`${BASE}/system/mdm/duplicates`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) throw new Error(String(res.status));
    return ((await res.json()) as { clusters: DuplicateCluster[] }).clusters;
  } catch {
    return [];
  }
}

/** Слить дубль в эталон (survivorship + архив дубля + alias). Обратимо через unmerge. */
export async function mergeCounterparties(
  survivorId: number,
  duplicateId: number,
): Promise<boolean> {
  try {
    const res = await fetch("/api/system/mdm/merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ survivor_id: survivorId, duplicate_id: duplicateId }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Расклеить ранее слитый дубль (вернуть активность, убрать merge-alias). */
export async function unmergeCounterparty(duplicateId: number): Promise<boolean> {
  try {
    const res = await fetch("/api/system/mdm/unmerge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ duplicate_id: duplicateId }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

// ── Группы (категории) номенклатуры — иерархия (parent_id) ───────────────────

/** Группа номенклатуры (узел дерева; parent_id=null → корень). */
export interface NomenclatureGroup {
  id: number;
  code: string;
  name: string;
  parent_id: number | null;
  is_active: boolean;
}

/** Узел дерева категорий (собирается из плоского списка на клиенте). */
export interface CategoryTreeNode extends NomenclatureGroup {
  children: CategoryTreeNode[];
}

/** Плоский список групп (SSR); `archived` — включая архивные. Дерево строит {@link buildCategoryTree}. */
export async function fetchNomenclatureGroups(
  opts: { archived?: boolean; roles?: string } = {},
): Promise<NomenclatureGroup[]> {
  try {
    const q = opts.archived ? "?archived=true" : "";
    const res = await fetch(`${BASE}/system/refs/nomenclature-groups${q}`, {
      cache: "no-store",
      headers: roleHeaders(opts.roles),
    });
    if (!res.ok) throw new Error(String(res.status));
    return (await res.json()) as NomenclatureGroup[];
  } catch {
    return [];
  }
}

/** Создать группу (клиент); `parent_id` пуст → корневая. */
export async function createNomenclatureGroup(group: {
  code: string;
  name: string;
  parent_id?: number | null;
}): Promise<boolean> {
  try {
    const res = await fetch("/api/system/refs/nomenclature-groups", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(group),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Изменить группу по коду (имя / перенос в другого родителя). */
export async function patchNomenclatureGroup(
  code: string,
  fields: { name?: string; parent_id?: number | null },
): Promise<boolean> {
  try {
    const res = await fetch(`/api/system/refs/nomenclature-groups/${encodeURIComponent(code)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Архивировать группу по коду (мягкое удаление). */
export async function archiveNomenclatureGroup(code: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/system/refs/nomenclature-groups/${encodeURIComponent(code)}`, {
      method: "DELETE",
    });
    return res.ok;
  } catch {
    return false;
  }
}

// ── Чистые хелперы (без I/O, тестируемые) ────────────────────────────────────

/** Плоский список справочников с прикреплённым отделом (для поиска/дерева). */
export function flattenCatalog(catalog: ReferenceCatalog): (ReferenceMeta & { department: string })[] {
  return Object.entries(catalog.departments).flatMap(([department, refs]) =>
    refs.map((r) => ({ ...r, department })),
  );
}

/** Текущая версия — та, у которой нет даты окончания (полуоткрытый интервал). */
export function isCurrentVersion(row: { end_date: string | null }): boolean {
  return row.end_date === null;
}

/** Версии по убыванию даты начала (новая — первой), как отдаёт backend-список. */
export function sortVersionsDesc<T extends { start_date: string }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => b.start_date.localeCompare(a.start_date));
}

/** Сколько всего дублей-кандидатов на слияние (members сверх эталона) во всех кластерах. */
export function totalDuplicates(clusters: DuplicateCluster[]): number {
  return clusters.reduce((sum, c) => sum + Math.max(0, c.members.length - 1), 0);
}

/** Собрать дерево категорий из плоского списка по `parent_id` (порядок входа сохраняется).
 * Узлы с отсутствующим/неактивным родителем поднимаются в корни (сироты не теряются). */
export function buildCategoryTree(groups: NomenclatureGroup[]): CategoryTreeNode[] {
  const byId = new Map<number, CategoryTreeNode>();
  for (const g of groups) byId.set(g.id, { ...g, children: [] });
  const roots: CategoryTreeNode[] = [];
  for (const node of byId.values()) {
    const parent = node.parent_id != null ? byId.get(node.parent_id) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  return roots;
}
