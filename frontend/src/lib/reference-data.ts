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

// ponytail: каталог тянет строки витрины одной страницей без пагинации — потолок
// строк; если выйдет за него (напр. >200 SKU), нужна пагинация/счётчик «N из M».
export const CATALOG_ROW_LIMIT = 200;

/** Развернуть конверт reference.query (`{result: [...]}`) в массив строк; иначе — пусто. */
export function rowsFromResult(payload: { result?: unknown } | null): Record<string, unknown>[] {
  return Array.isArray(payload?.result) ? (payload.result as Record<string, unknown>[]) : [];
}

/** Строки master-data витрины по ключу через `reference.query` (SSR, абсолютный URL).
 *
 * Контрагенты/контакты/номенклатура/сотрудники не имеют CRUD-роутера — читаются
 * структурным запросом. Не-200 → пусто. Клиентский путь — `runReferenceQuery`. */
export async function fetchRefRowsByKey(
  key: string,
  roles?: string,
  limit = CATALOG_ROW_LIMIT,
): Promise<Record<string, unknown>[]> {
  try {
    const res = await fetch(`${BASE}/system/references/query`, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...roleHeaders(roles) },
      body: JSON.stringify({ ref: key, limit }),
    });
    if (!res.ok) throw new Error(String(res.status));
    return rowsFromResult(await res.json());
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

/** Источник эталона (откуда пришла запись): 1С/Bitrix/merge. */
export interface CounterpartyAlias {
  source: string;
  external_ref: string;
  created_at: string;
}

/** Запись аудит-журнала по контрагенту (проекция доменных событий). */
export interface CounterpartyAudit {
  id: number;
  ts: string;
  actor: string;
  action: string;
  detail: Record<string, unknown>;
}

/** Происхождение одного поля (M2): откуда значение и когда записано. */
export interface FieldProvenance {
  source: string; // egr | erp | manual | 1c | bitrix
  at: string | null; // ISO-дата записи значения
}

/** Карта происхождения по полям записи: `{field: {source, at}}` (M2). */
export type Provenance = Record<string, FieldProvenance>;

/** Одно касание клиента в 360°-истории (звонок/письмо/сделка), M5. */
export interface Touch {
  kind: string; // call | deal | message | ...
  ts: string;
  channel: string | null;
  direction: string | null; // in | out | null
  title: string;
  ref: string; // напр. "call:5" / "deal:12"
}

/** Сводка касаний: счётчики по типам + последний контакт (M5). */
export interface TouchSummary {
  calls: number;
  deals: number;
  messages: number;
  last_contact: string | null;
}

/** Карточка эталона контрагента (golden record): реквизиты + источники + дубли + контакты + аудит + 360°. */
export interface CounterpartyCard {
  id: number;
  name: string;
  unp: string | null;
  is_active: boolean;
  merged_into_id: number | null;
  provenance: Provenance; // M2: происхождение по полям
  aliases: CounterpartyAlias[];
  merged_duplicates: DuplicateMember[];
  contacts: { id: number; full_name: string; phone: string | null; email: string | null; is_primary: boolean }[];
  audit: CounterpartyAudit[];
  touches: Touch[]; // M5: 360°-история (пусто, если sales-фасад не подключён)
  touch_summary: TouchSummary | null;
}

/** Карточка одного эталона контрагента (SSR) — экран карточки/MDM. `null` — нет записи. */
export async function fetchCounterpartyCard(
  id: number,
  roles?: string,
): Promise<CounterpartyCard | null> {
  try {
    const res = await fetch(`${BASE}/system/mdm/counterparty/${id}`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) throw new Error(String(res.status));
    return (await res.json()) as CounterpartyCard;
  } catch {
    return null;
  }
}

// ── Журнал исходящего синка ERP → 1С (M3) ────────────────────────────────────

/** Запись журнала выгрузки: что/куда/статус/когда/ошибка (sync_link). */
export interface SyncJournalEntry {
  id: number;
  entity_type: string; // counterparty | sku
  entity_id: number;
  system: string; // 1c
  origin: string; // erp | 1c | bitrix
  direction: string; // out | in
  state: string; // pending | synced | error
  external_ref: string | null;
  last_synced_at: string | null;
  error_text: string | null;
}

/** Журнал исходящей выгрузки ERP → 1С (SSR). Под правом integrations.sync. */
export async function fetchSyncJournal(roles?: string): Promise<SyncJournalEntry[]> {
  try {
    const res = await fetch(`${BASE}/integrations/1c/sync-journal`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) throw new Error(String(res.status));
    return ((await res.json()) as { entries: SyncJournalEntry[] }).entries;
  } catch {
    return [];
  }
}

// ── Карточка номенклатуры (master-data витрина SKU, M4) ──────────────────────

/** Карточка номенклатуры: горячие типизированные поля + JSON-хвост + себестоимость (фасад). */
export interface SkuCard {
  code: string;
  title: string;
  unit: string | null;
  category_id: number | null;
  weight_kg: number | null;
  tnved_code: string | null;
  shelf_life_days: number | null;
  is_active: boolean;
  attributes: Record<string, unknown>; // переменные характеристики (JSONB-хвост)
  provenance: Provenance; // происхождение по полям (M2)
  landed_cost: number | null; // себес партии; null — нет расчёта/модуль не подключён (не 0)
}

/** Карточка одной номенклатуры по коду (SSR). `null` — нет записи/нет доступа. */
export async function fetchSkuCard(code: string, roles?: string): Promise<SkuCard | null> {
  try {
    const res = await fetch(`${BASE}/system/sku/${encodeURIComponent(code)}`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) throw new Error(String(res.status));
    return (await res.json()) as SkuCard;
  } catch {
    return null;
  }
}

// ── ТН ВЭД: резолв таможенных ставок на дату (вход landed cost) ──────────────

/** Ставки по коду ТН ВЭД на дату: пошлина (ЕТТ) + НДС (резолвлен из ref_vat_rate). */
export interface TnvedRates {
  code: string;
  name: string;
  duty_rate: number; // ввозная пошлина %, ЕТТ ЕАЭС
  vat_code: string | null;
  vat_rate: number | null; // ставка НДS % на дату; null — не задана
  excise: string | null;
  unit: string | null;
  as_of: string; // дата, на которую резолвлены ставки
}

/** Ставки ТН ВЭД на дату `on` (YYYY-MM-DD) — вход расчёта себестоимости. `null` — нет версии. */
export async function fetchTnvedRates(
  code: string,
  on: string,
  roles?: string,
): Promise<TnvedRates | null> {
  try {
    const res = await fetch(
      `${BASE}/system/tnved/lookup?code=${encodeURIComponent(code)}&on=${encodeURIComponent(on)}`,
      { cache: "no-store", headers: roleHeaders(roles) },
    );
    if (!res.ok) throw new Error(String(res.status));
    return (await res.json()) as TnvedRates;
  } catch {
    return null;
  }
}

// ── Правила слияния (survivorship, M2) ───────────────────────────────────────

/** Правило слияния для одного поля: стратегия + (для source_priority) порядок источников. */
export interface SurvivorshipRule {
  id: number;
  entity_type: string; // counterparty | sku
  field: string;
  strategy: string; // source_priority | manual_only | most_recent | non_empty_wins
  source_priority: string[];
}

/** Правила слияния (SSR), `entityType` — фильтр (counterparty/sku); пусто — все. */
export async function fetchSurvivorshipRules(
  entityType?: string,
  roles?: string,
): Promise<SurvivorshipRule[]> {
  try {
    const q = entityType ? `?entity_type=${encodeURIComponent(entityType)}` : "";
    const res = await fetch(`${BASE}/system/mdm/rules${q}`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) throw new Error(String(res.status));
    return ((await res.json()) as { rules: SurvivorshipRule[] }).rules;
  } catch {
    return [];
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
