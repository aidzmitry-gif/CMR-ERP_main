import { daysInStage, ensureLostStage, STUCK_DAYS } from "@/lib/board";
import { progressionIndex, STAGE_BY_ID, TERMINAL_STAGES } from "@/lib/sales-stages";
import { DEAL_DETAIL, getDealDetail, KPIS, STAGES } from "@/lib/mock-data";
import type { Deal, DealDetail, Kpi, KpiIcon, KpiTone, Lead, LeadAttachment, LeadHandoffStat, LeadPlan, LeadSourceStat, LeadStatus, LossReason, Manager, Stage } from "@/lib/types";
import { toPriority } from "@/lib/types";

// Базовый URL бэкенда для серверных компонентов (SSR-fetch).
const BASE = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

// SSR-фетчи ходят на BASE напрямую, минуя /api-прокси, поэтому роль надо пробросить
// заголовком вручную (роль читает серверный хелпер `role-server.ts` из cookie). На клиенте
// (вызовы через /api/*) роль добавляет прокси `app/api/[...path]/route.ts`.
// Опциональный accessToken — OIDC Bearer (см. auth-headers-server / TOKEN_COOKIE).
function roleHeaders(roles?: string, accessToken?: string): Record<string, string> | undefined {
  const headers: Record<string, string> = {};
  if (roles) headers["X-User-Roles"] = roles;
  if (accessToken) headers.Authorization = "Bearer " + accessToken;
  return Object.keys(headers).length ? headers : undefined;
}

interface ApiDeal {
  id: number;
  number: string;
  title: string;
  counterparty: string;
  amount: number;
  priority: string;
  stage: string;
  owner: string;
  next_step: string | null;
  next_step_at?: string | null;
  deal_date: string | null;
  closed_date: string | null;
  focus: boolean;
  starred: boolean;
  // Сделки 2.0 — дополнения DealRead (SALES-40/43/44); бэкенд может их не прислать (старый контракт).
  probability?: number | null;
  expected_close_date?: string | null;
  stage_changed_at?: string | null;
  lost_reason_code?: string | null;
  lost_comment?: string | null;
  // Крайняя дата отгрузки + штраф за опоздание (дата уходит сигналом в закупки).
  ship_deadline?: string | null;
  penalty_rate_pct?: number | null;
  penalty_cap_pct?: number | null;
  penalty_terms?: string | null;
  // Живой бейдж «🚚 под приход» (П6 UI ТЗ) — из аудита событий, не колонка БД.
  supply_arrived_at?: string | null;
  supply_arrived_sku?: string | null;
}

interface ApiStage {
  id: string;
  title: string;
  color: string;
  count: number;
  sum: number;
  deals: ApiDeal[];
}

function mapDeal(d: ApiDeal): Deal {
  return {
    id: String(d.id),
    number: d.number,
    company: d.counterparty,
    description: d.title,
    // Number(d.amount ?? 0) — симметрично fetchDealDetail; страховка от null/NaN в борде.
    amount: Number(d.amount ?? 0),
    priority: toPriority(d.priority),
    owner: d.owner,
    date: d.deal_date ?? undefined,
    closedDate: d.closed_date ?? undefined,
    nextStep: d.next_step ?? undefined,
    nextStepAt: d.next_step_at ?? undefined,
    starred: d.starred,
    // Сделки 2.0: вероятность/прогноз (SALES-44), история стадий (SALES-43), причина отказа (SALES-40)
    probability: d.probability ?? undefined,
    expectedCloseDate: d.expected_close_date ?? undefined,
    stageChangedAt: d.stage_changed_at ?? undefined,
    lostReasonCode: d.lost_reason_code ?? undefined,
    lostComment: d.lost_comment ?? undefined,
    supplyArrivedAt: d.supply_arrived_at ?? undefined,
    supplyArrivedSku: d.supply_arrived_sku ?? undefined,
  };
}

/** Доска сделок из API; при недоступности бэкенда — fallback на mock.
 * В обоих случаях гарантируем колонку «отказ» (SALES-40) через {@link ensureLostStage}. */
export async function fetchBoardStages(roles?: string, funnel?: string): Promise<Stage[]> {
  return (await fetchBoardResult(roles, funnel)).stages;
}

/** Доска + признак фоллбэка: `demo=true` — backend недоступен, отданы мок-стадии
 * (STAGES из mock-data). Страница доски показывает по нему плашку «демо-данные»,
 * чтобы фоллбэк не выглядел как реальная воронка. */
export async function fetchBoardResult(
  roles?: string,
  funnel?: string,
): Promise<{ stages: Stage[]; demo: boolean }> {
  try {
    const qs = funnel ? `?funnel=${encodeURIComponent(funnel)}` : "";
    const res = await fetch(`${BASE}/sales/board${qs}`, { cache: "no-store", headers: roleHeaders(roles) });
    if (!res.ok) throw new Error(String(res.status));
    const data = (await res.json()) as { stages: ApiStage[] };
    return {
      demo: false,
      stages: ensureLostStage(
        data.stages.map((s) => ({
          id: s.id,
          title: s.title,
          color: s.color,
          count: s.count,
          sum: s.sum,
          deals: s.deals.map(mapDeal),
        })),
      ),
    };
  } catch {
    return { stages: ensureLostStage(STAGES), demo: true };
  }
}

/** Стадия воронки из редактора (бэк sales.stage) — полный ряд для CRUD. */
export interface StageRow {
  code: string;
  title: string;
  sort_order: number;
  probability: number;
  kind: "normal" | "won" | "cond_lost" | "lost";
  color: string;
  is_active: boolean;
  funnel: string;
}

/** Воронка sales (мульти-воронки): код + титул + счётчик активных сделок. */
export interface FunnelRow {
  code: string;
  title: string;
  active_deals: number;
}

/** Сводка «передано в исполнение» по выигранной сделке (П10 ТЗ). */
export interface DealHandoff {
  deal_id: number;
  number: string;
  counterparty: string;
  amount: number;
  owner: string;
  funnel: string;
  items: { sku_code: string; title: string; qty: number }[];
  gross_profit: number | null;
  handed_off_at: string | null;
}

/** Прочитать handoff-сводку по сделке; null — событие ещё не эмитнуто. */
export async function fetchDealHandoff(dealId: string): Promise<DealHandoff | null> {
  try {
    const res = await fetch(`/api/sales/deals/${encodeURIComponent(dealId)}/handoff`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    const body = await res.json();
    return body as DealHandoff | null;
  } catch {
    return null;
  }
}

export type PlanStatus = "draft" | "pending_approval" | "approved" | "rejected";

/** Личный план показателя продавца (PlanTarget). */
export interface PlanRow {
  id: number;
  owner_id: number;
  metric: string;
  period_type: "day" | "week" | "month" | "quarter" | "year";
  period_key: string;
  target: number;
  status: PlanStatus;
  approved_by: string | null;
  approved_at: string | null;
}

/** Прочитать планы по фильтрам (полная страница плана). */
export async function fetchPlans(params: {
  owner_id?: number;
  period_type?: string;
  period_key?: string;
}): Promise<PlanRow[]> {
  try {
    const qs = new URLSearchParams();
    if (params.owner_id != null) qs.set("owner_id", String(params.owner_id));
    if (params.period_type) qs.set("period_type", params.period_type);
    if (params.period_key) qs.set("period_key", params.period_key);
    const res = await fetch(`/api/sales/plans?${qs.toString()}`, { cache: "no-store" });
    if (!res.ok) throw new Error(String(res.status));
    return (await res.json()) as PlanRow[];
  } catch {
    return [];
  }
}

/** Поставить/изменить draft план по (owner, metric, period). */
export async function upsertPlan(input: Omit<PlanRow, "id" | "status" | "approved_by" | "approved_at">): Promise<PlanRow | null> {
  try {
    const res = await fetch("/api/sales/plans", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!res.ok) return null;
    return (await res.json()) as PlanRow;
  } catch {
    return null;
  }
}

export async function submitPlan(planId: number): Promise<boolean> {
  try {
    const res = await fetch(`/api/sales/plans/${planId}/submit`, { method: "POST" });
    return res.ok;
  } catch {
    return false;
  }
}

export async function decidePlan(planId: number, approved: boolean, comment?: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/sales/plans/${planId}/decide`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved, comment }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Список воронок sales для переключателя на доске (клиент, через /api-прокси). */
export async function fetchFunnels(): Promise<FunnelRow[]> {
  try {
    const res = await fetch("/api/sales/funnels", { cache: "no-store" });
    if (!res.ok) throw new Error(String(res.status));
    return (await res.json()) as FunnelRow[];
  } catch {
    return [];
  }
}

/** То же для SSR (page.tsx «Все вместе»): относительный `/api/...` на сервере не работает —
 * ходим на BASE напрямую с ручным пробросом роли (как fetchBoardResult/fetchKpis). */
export async function fetchFunnelsServer(roles?: string): Promise<FunnelRow[]> {
  try {
    const res = await fetch(`${BASE}/sales/funnels`, {
      cache: "no-store",
      headers: roleHeaders(roles),
    });
    if (!res.ok) throw new Error(String(res.status));
    return (await res.json()) as FunnelRow[];
  } catch {
    return [];
  }
}

/** Создать стадию (редактор стадий). */
export async function createStage(input: StageRow): Promise<boolean> {
  try {
    const res = await fetch("/api/sales/stages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Частично обновить стадию (имя/порядок/вероятность/тип/цвет/активность). */
export async function updateStage(code: string, patch: Partial<StageRow>): Promise<boolean> {
  try {
    const res = await fetch(`/api/sales/stages/${encodeURIComponent(code)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Удалить стадию; 409 (с detail), если в стадии есть сделки. */
export async function deleteStage(code: string): Promise<{ ok: boolean; detail?: string }> {
  try {
    const res = await fetch(`/api/sales/stages/${encodeURIComponent(code)}`, { method: "DELETE" });
    if (res.ok) return { ok: true };
    const body = (await res.json().catch(() => ({}))) as { detail?: string };
    return { ok: false, detail: body.detail };
  } catch {
    return { ok: false };
  }
}

/** Детальная карточка сделки из API; fallback — mock по id. */
/** Активная стадия сделки для DealDetail: idx прогрессии + заголовок (канон) +
 *  «дней в стадии»/«протухает» (SALES-43, из stage_changed_at). undefined — нет канон-стадии. */
function dealStage(stageId: string, stageChangedAt?: string | null): DealDetail["stage"] {
  const s = STAGE_BY_ID[stageId];
  if (!s) return undefined;
  const days = daysInStage(stageChangedAt ?? undefined, Date.now());
  return {
    idx: progressionIndex(stageId),
    id: stageId,
    title: s.title,
    daysInStage: days ?? undefined,
    isStale: days != null && days >= STUCK_DAYS && !TERMINAL_STAGES.has(stageId),
  };
}

export async function fetchDealDetail(id: string, roles?: string): Promise<DealDetail> {
  try {
    const res = await fetch(`${BASE}/sales/deals/${id}`, { cache: "no-store", headers: roleHeaders(roles) });
    if (!res.ok) throw new Error(String(res.status));
    const d = (await res.json()) as ApiDeal & {
      items?: { title: string; last_price: number | null; min_price: number | null }[];
      counterparty_ref?: {
        id: number;
        name: string;
        unp: string | null;
        sources: string[];
        is_active: boolean;
        merged_into_id: number | null;
      } | null;
    };
    const cp = d.counterparty_ref;
    return {
      number: d.number,
      company: d.counterparty,
      // Контрагент из MDM (резолв по имени на бэке): id/УНП/источники для <SourceTag> и
      // связанных блоков. None с бэка → undefined → honest-empty (нет в витрине).
      counterparty: cp
        ? {
            id: cp.id,
            unp: cp.unp ?? undefined,
            sourceSystem: (["erp", "1c", "bitrix"] as const).find((s) => cp.sources.includes(s)),
            isGolden: cp.is_active && cp.merged_into_id == null,
            mergedIntoId: cp.merged_into_id ?? undefined,
          }
        : undefined,
      description: d.title,
      // Number(d.amount ?? 0) — на пустой/null сделке formatByn не нарисует «NaN BYN».
      amount: Number(d.amount ?? 0),
      priority: toPriority(d.priority),
      nextStep: d.next_step ?? DEAL_DETAIL.nextStep,
      contact: d.owner || DEAL_DETAIL.contact,
      datetime: `${d.deal_date ?? d.closed_date ?? ""} • 14:00`,
      // позиции номенклатуры с ценами клиенту (Price Engine); сообщения — отдельный блок
      itemsTitle: "Номенклатура",
      items: (d.items ?? []).map((i) => ({
        title: i.title,
        lastPrice: i.last_price ?? undefined,
        minPrice: i.min_price ?? undefined,
      })),
      messages: DEAL_DETAIL.messages,
      focus: d.focus,
      starred: d.starred,
      dealDate: d.deal_date ?? "",
      // Активная стадия из бэка: idx прогрессии + заголовок (канон sales-stages.ts) +
      // «дней в стадии»/«протухает» (SALES-43) из stage_changed_at.
      stage: dealStage(d.stage, d.stage_changed_at),
      // Вероятность/прогноз (SALES-44): явный override; нет — UI возьмёт дефолт по стадии.
      probability: d.probability ?? undefined,
      expectedCloseDate: d.expected_close_date ?? undefined,
      // Причина отказа (SALES-40) — бэк отдаёт в DealRead, detail её раньше ронял.
      lostReasonCode: d.lost_reason_code ?? undefined,
      lostComment: d.lost_comment ?? undefined,
      // Крайняя дата отгрузки + штраф за опоздание (дата уходит в закупки).
      shipDeadline: d.ship_deadline ?? undefined,
      penaltyRatePct: d.penalty_rate_pct ?? undefined,
      penaltyCapPct: d.penalty_cap_pct ?? undefined,
      penaltyTerms: d.penalty_terms ?? undefined,
    };
  } catch {
    return getDealDetail(id);
  }
}

export interface DealInput {
  number: string;
  title: string;
  counterparty: string;
  amount: number;
  priority: string;
  stage: string;
  owner: string;
  next_step?: string;
}

export interface SkuOption {
  id: number;
  code: string;
  title: string;
  unit: string;
}

export interface DealItemFull {
  id: number;
  sku_id: number;
  code: string;
  title: string;
  unit: string;
  qty: number;
  last_price: number | null;
  min_price: number | null;
}

/** Справочник номенклатуры для подбора (клиент, через /api). */
export async function fetchSkus(forPicker = true): Promise<SkuOption[]> {
  try {
    const qs = forPicker ? "?for_picker=1" : "";
    const res = await fetch(`/api/sales/skus${qs}`, { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as SkuOption[];
  } catch {
    return [];
  }
}

/** Строка остатка/цены по складу (demo-зеркало 1С, владелец — integrations). */
export interface StockRow {
  sku_code: string;
  warehouse: string;
  qty_available: number;
  qty_reserved: number;
  qty_forecast: number; // «в пути» / прогноз прихода
  price: number;
  cost?: number | null; // себестоимость из 1С (для маржи «в наличии»); null — не дана
}

/** Остатки и цены по складам (для подбора товара со склада в окне звонка). */
export async function fetchStock(): Promise<StockRow[]> {
  try {
    const res = await fetch("/api/integrations/1c/stock", { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as StockRow[];
  } catch {
    return [];
  }
}

/**
 * Зафиксировать котировку цены SKU клиенту (Price Engine, POST /prices).
 * Нужна, чтобы позиция сделки знала цену: deal-items берёт last/min из PriceQuote
 * по (sku_code, counterparty). Пишем цену со склада на контрагента сделки.
 */
export async function createPriceQuote(
  skuCode: string,
  counterparty: string,
  price: number,
): Promise<boolean> {
  try {
    const res = await fetch("/api/sales/prices", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sku_code: skuCode, counterparty, price }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Позиции номенклатуры сделки (с ценами клиенту). */
export async function fetchDealItems(dealId: string): Promise<DealItemFull[]> {
  try {
    const res = await fetch(`/api/sales/deals/${dealId}/items`, { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as DealItemFull[];
  } catch {
    return [];
  }
}

/** Позиции последней сделки того же контрагента — «повторить прошлый заказ»
 * (honest empty [], если предыдущих заказов нет — не 404). */
export async function fetchLastOrder(dealId: string): Promise<DealItemFull[]> {
  try {
    const res = await fetch(`/api/sales/deals/${dealId}/repeat-last-order`, { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as DealItemFull[];
  } catch {
    return [];
  }
}

/** Добавить позицию в сделку. */
export async function addDealItem(dealId: string, skuId: number, qty: number): Promise<boolean> {
  try {
    const res = await fetch(`/api/sales/deals/${dealId}/items`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sku_id: skuId, qty }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Изменить количество в позиции. */
export async function updateDealItem(itemId: number, qty: number): Promise<boolean> {
  try {
    const res = await fetch(`/api/sales/deal-items/${itemId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ qty }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Удалить позицию из сделки. */
export async function deleteDealItem(itemId: number): Promise<boolean> {
  try {
    const res = await fetch(`/api/sales/deal-items/${itemId}`, { method: "DELETE" });
    return res.ok;
  } catch {
    return false;
  }
}

// --- Задачи по сделке (SALES-41) ---

export interface DealTaskView {
  id: number;
  deal_id: number;
  title: string;
  kind: string;
  assignee_id: number | null;
  due_at: string | null;
  status: string; // open | done | canceled
  result: string | null;
  overdue: boolean;
}

/** Задачи сделки (открытые — первыми; overdue — флаг просрочки). */
export async function fetchDealTasks(dealId: string): Promise<DealTaskView[]> {
  try {
    const res = await fetch(`/api/sales/deals/${dealId}/tasks`, { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as DealTaskView[];
  } catch {
    return [];
  }
}

/** Поставить задачу по сделке. */
export async function createDealTask(
  dealId: string,
  task: { title: string; kind?: string; due_at?: string | null },
): Promise<boolean> {
  try {
    const res = await fetch(`/api/sales/deals/${dealId}/tasks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(task),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Отметить задачу выполненной. */
export async function completeDealTask(taskId: number, result?: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/sales/tasks/${taskId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "done", result: result ?? "" }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export interface DealContact {
  id: number;
  full_name: string;
  phone: string | null;
  email: string | null;
  is_primary: boolean;
}

/** Контакты контрагента сделки (основной — первым). */
export async function fetchContacts(dealId: string): Promise<DealContact[]> {
  try {
    const res = await fetch(`/api/sales/deals/${dealId}/contacts`, { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as DealContact[];
  } catch {
    return [];
  }
}

/** Добавить контакт контрагенту сделки. */
export async function addContact(
  dealId: string,
  contact: { full_name: string; phone?: string; email?: string; is_primary?: boolean },
): Promise<boolean> {
  try {
    const res = await fetch(`/api/sales/deals/${dealId}/contacts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(contact),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Назначить контакт основным. */
export async function setPrimaryContact(contactId: number): Promise<boolean> {
  try {
    const res = await fetch(`/api/sales/contacts/${contactId}/primary`, { method: "PATCH" });
    return res.ok;
  } catch {
    return false;
  }
}

export interface ChatItem {
  deal_id: number;
  number: string;
  company: string;
  last_text: string;
  channel: string;
  direction: string;
  unread?: number;
}

/** Диалоги для панели «Чаты и дела» (сделки с последним сообщением). */
export async function fetchChats(): Promise<ChatItem[]> {
  try {
    const res = await fetch("/api/sales/chats", { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as ChatItem[];
  } catch {
    return [];
  }
}

export interface SystemEvent {
  id: number;
  event_type: string;
  created_at: string;
  processed: boolean;
}

/** Последние доменные события (для уведомлений в шапке). */
export async function fetchEvents(): Promise<SystemEvent[]> {
  try {
    const res = await fetch("/api/system/events", { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as SystemEvent[];
  } catch {
    return [];
  }
}

export interface RegistryInfo {
  unp: string;
  name: string;
  address: string;
  status: string;
}

/** Подтянуть контрагента по УНП из реестра ЕГР (клиент, через /api). */
export async function lookupCounterparty(unp: string): Promise<RegistryInfo | null> {
  try {
    const res = await fetch(`/api/integrations/egr/${encodeURIComponent(unp)}`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as RegistryInfo;
  } catch {
    return null;
  }
}

/** Создать сделку (клиентский вызов через прокси /api). */
export async function createDeal(input: DealInput): Promise<Deal | null> {
  try {
    const res = await fetch("/api/sales/deals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!res.ok) return null;
    return mapDeal((await res.json()) as ApiDeal);
  } catch {
    return null;
  }
}

/** Сменить стадию сделки (drag&drop). */
export async function updateDealStage(id: string, stage: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/sales/deals/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Частично обновить сделку (фокус/звезда/приоритет/поля). */
export async function updateDeal(
  id: string,
  fields: Record<string, unknown>,
): Promise<boolean> {
  try {
    const res = await fetch(`/api/sales/deals/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Справочник причин отказа (SALES-40) для выпадашки модалки.
 * При недоступности бэка — пусто; вызывающий код берёт локальный fallback (`LOSS_REASONS`). */
export async function fetchLossReasons(): Promise<LossReason[]> {
  try {
    const res = await fetch("/api/sales/loss-reasons", { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as LossReason[];
  } catch {
    return [];
  }
}

/** Закрыть сделку в отказ (SALES-40): причина обязательна, комментарий — опционально.
 * Fire-and-forget, как updateDealStage: UI обновляется оптимистично, бэк — best-effort. */
export async function loseDeal(id: string, reasonCode: string, comment?: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/sales/deals/${id}/lose`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason_code: reasonCode, comment }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

interface ApiKpi {
  key: string;
  title: string;
  target: number;
  actual: number;
  percent: number;
  unit: string;
  icon: string;
  tone: string;
}

function mapKpi(k: ApiKpi): Kpi {
  return {
    id: k.key,
    label: k.title,
    value: k.actual,
    target: k.target,
    percent: k.percent,
    money: k.unit === "money",
    icon: k.icon as KpiIcon,
    tone: k.tone as KpiTone,
  };
}

/** KPI «План на сегодня» из API (SSR); fallback на mock. */
export async function fetchKpis(roles?: string): Promise<Kpi[]> {
  try {
    const res = await fetch(`${BASE}/sales/kpis`, { cache: "no-store", headers: roleHeaders(roles) });
    if (!res.ok) throw new Error(String(res.status));
    const data = (await res.json()) as ApiKpi[];
    return data.length ? data.map(mapKpi) : KPIS;
  } catch {
    return KPIS;
  }
}

/** Перечитать KPI с клиента за период (после отметки активности / смены периода). */
export async function getKpis(period = "day"): Promise<Kpi[]> {
  try {
    const res = await fetch(`/api/sales/kpis?period=${encodeURIComponent(period)}`, { cache: "no-store" });
    if (!res.ok) throw new Error(String(res.status));
    return ((await res.json()) as ApiKpi[]).map(mapKpi);
  } catch {
    return [];
  }
}

/** Отметить факт активности (для роста KPI). */
export async function logActivity(kpiKey: string, value = 1): Promise<boolean> {
  try {
    const res = await fetch("/api/sales/activities", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kpi_key: kpiKey, value }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export interface Approval {
  id: number;
  kind: string;
  entity_ref: string;
  subject: string;
  route: string;
  status: string;
  requested_by: string;
  decided_by: string | null;
}

/** Согласования по сделке (клиент, через /api). */
export async function fetchApprovals(params: { entityRef?: string; status?: string } = {}): Promise<Approval[]> {
  try {
    const q = new URLSearchParams();
    if (params.entityRef) q.set("entity_ref", params.entityRef);
    if (params.status) q.set("status", params.status);
    const res = await fetch(`/api/approvals?${q.toString()}`, { cache: "no-store" });
    if (!res.ok) throw new Error(String(res.status));
    return (await res.json()) as Approval[];
  } catch {
    return [];
  }
}

/** Отправить сделку на согласование. */
export async function requestApproval(dealId: string, kind: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/sales/deals/${dealId}/request-approval`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, requested_by: "Менеджер" }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Принять решение по согласованию. */
export async function decideApproval(id: number, approved: boolean, by: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/approvals/${id}/${approved ? "approve" : "reject"}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ by }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export interface DealDoc {
  id: number;
  kind: string;
  number: string;
  status: string;
  onec_ref: string | null;
  amount: number;
  valid_until: string | null; // SALES-51: срок действия счёта (резерв), ISO-дата
  reserve_status: string; // none | reserved | consumed | released
}

/** Документы сделки (счета/договоры/заказы) — клиент, через /api. */
export async function fetchDocuments(dealId: string): Promise<DealDoc[]> {
  try {
    const res = await fetch(`/api/sales/deals/${dealId}/documents`, { cache: "no-store" });
    if (!res.ok) throw new Error(String(res.status));
    return (await res.json()) as DealDoc[];
  } catch {
    return [];
  }
}

/** Сформировать документ сделки (счёт/договор/заказ). Договор уходит на согласование. */
export async function createDocument(dealId: string, kind: string): Promise<DealDoc | null> {
  try {
    const res = await fetch(`/api/sales/deals/${dealId}/documents`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, requested_by: "Менеджер" }),
    });
    if (!res.ok) return null;
    return (await res.json()) as DealDoc;
  } catch {
    return null;
  }
}

/** Итог выставления документа: сообщение для тоста + URL печатной формы (у счёта).
 * Единый источник текста/URL для трёх мест (окно звонка, drawer-preview, модалка подбора)
 * — чтобы контракт createDocument/рендера не расходился по копиям. Само окно печати
 * вызывающий открывает СИНХРОННО (до await), иначе popup-блокировщик съест вкладку. */
export interface DocIssueResult {
  ok: boolean;
  message: string;
  renderUrl?: string;
}

export async function issueDocument(dealId: string, kind: "invoice" | "contract"): Promise<DocIssueResult> {
  const doc = await createDocument(dealId, kind);
  if (!doc) {
    return { ok: false, message: kind === "invoice" ? "⚠️ Не удалось выставить счёт" : "⚠️ Не удалось создать договор" };
  }
  return kind === "invoice"
    ? { ok: true, message: `✅ Счёт ${doc.number} выставлен`, renderUrl: `/api/sales/documents/${doc.id}/render` }
    : { ok: true, message: `✅ Договор ${doc.number} отправлен на согласование` };
}

/** Решение по документу на согласовании (договор): провести в 1С или отклонить. */
export async function decideDocument(docId: number, approved: boolean, by: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/sales/documents/${docId}/decide`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved, by }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export interface DealMsg {
  id: number;
  channel: string;
  direction: string;
  author: string;
  text: string;
  created_at: string;
}

/** Омниканальная история переписки по сделке (клиент, через /api). */
export async function fetchMessages(dealId: string): Promise<DealMsg[]> {
  try {
    const res = await fetch(`/api/sales/deals/${dealId}/messages`, { cache: "no-store" });
    if (!res.ok) throw new Error(String(res.status));
    return (await res.json()) as DealMsg[];
  } catch {
    return [];
  }
}

/** Отправить сообщение по сделке (канал + текст). */
export async function sendMessage(dealId: string, channel: string, text: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/sales/deals/${dealId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channel, text, author: "Менеджер", direction: "out" }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** AI-черновик ответа клиенту (AI-слой, Итерация 1). null — AI выключен / ошибка. */
export async function aiDraftReply(dealId: string): Promise<string | null> {
  try {
    const res = await fetch(`/api/sales/deals/${dealId}/ai/draft-reply`, { method: "POST" });
    if (!res.ok) return null;
    return ((await res.json()) as { text: string }).text;
  } catch {
    return null;
  }
}

/** AI-ассистент сделки: резюме / следующий шаг. null — AI выключен / ошибка. */
export async function aiAssist(dealId: string, kind: string): Promise<string | null> {
  try {
    const res = await fetch(`/api/sales/deals/${dealId}/ai/assist`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind }),
    });
    if (!res.ok) return null;
    return ((await res.json()) as { text: string }).text;
  } catch {
    return null;
  }
}

// ──────────────────────── Телефония (SALES-50) ────────────────────────

/** Карточка звонка из SSE-потока `/sales/calls/stream` (плоский dict backend `_card`). */
export interface CallCard {
  id: number;
  call_id: string;
  direction: string; // in | out
  phone: string | null;
  did?: string | null;
  agent_ext?: string | null;
  owner: string;
  counterparty_id?: number | null;
  contact_id?: number | null;
  deal_id?: number | null;
  status: string; // ringing | answered | missed | busy | ended | failed
  duration_sec?: number | null;
  recording_url?: string | null;
}

/** Запись журнала звонков (CallOut). */
export interface CallRow {
  id: number;
  call_id: string;
  direction: string;
  phone_e164: string | null;
  owner: string;
  status: string;
  result?: string | null;
  comment?: string | null;
  deal_id?: number | null;
  duration_sec?: number | null;
  started_at: string;
}

/**
 * Подписка на поток карточек звонков продавца (всплывающее окно входящего).
 * EventSource ходит на /api-прокси (он добавляет роль из cookie + стримит SSE).
 * Возвращает функцию отписки.
 */
export function subscribeCalls(owner: string | undefined, onCard: (card: CallCard) => void): () => void {
  // SSR / тестовая среда (jsdom) без EventSource — подписка не нужна, возвращаем no-op.
  if (typeof EventSource === "undefined") return () => {};
  const url = owner
    ? `/api/sales/calls/stream?owner=${encodeURIComponent(owner)}`
    : "/api/sales/calls/stream";
  const es = new EventSource(url);
  es.onmessage = (e) => {
    try {
      onCard(JSON.parse(e.data) as CallCard);
    } catch {
      /* heartbeat/комментарий потока — игнор */
    }
  };
  return () => es.close();
}

async function postCall(url: string, body: unknown): Promise<boolean> {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Журнал звонков с фильтрами (клиент, через /api). */
export async function fetchCalls(
  params: { status?: string; owner?: string; date?: string } = {},
): Promise<CallRow[]> {
  try {
    const q = new URLSearchParams(
      Object.entries(params).filter(([, v]) => Boolean(v)) as [string, string][],
    ).toString();
    const res = await fetch(`/api/sales/calls${q ? `?${q}` : ""}`, { cache: "no-store" });
    if (!res.ok) throw new Error(String(res.status));
    return (await res.json()) as CallRow[];
  } catch {
    return [];
  }
}

/** Заметка по звонку. */
export async function callComment(id: number, comment: string): Promise<boolean> {
  return postCall(`/api/sales/calls/${id}/comment`, { comment });
}

/** Итог/классификация звонка. */
export async function callResult(id: number, result: string): Promise<boolean> {
  return postCall(`/api/sales/calls/${id}/result`, { result });
}

/** Привязать звонок к сделке (deal_id) или создать новую (create=true). */
export async function callLinkDeal(
  id: number,
  body: { deal_id?: number; create?: boolean },
): Promise<boolean> {
  return postCall(`/api/sales/calls/${id}/link-deal`, body);
}

/** Симуляция входящего звонка (dev): прямой приём события телефонии, минуя АТС. */
export async function triggerIncomingCall(payload: Record<string, unknown>): Promise<boolean> {
  return postCall("/api/sales/telephony/incoming", payload);
}

interface ApiLead {
  id: number;
  source: string;
  name: string;
  company: string;
  phone: string | null;
  email: string | null;
  region: string;
  product: string;
  message: string;
  status: string;
  score: number;
  qualification: string;
  reason: string;
  assigned_to: string;
  funnel: string;
  deal_id: number | null;
  reject_reason: string;
  next_step_at: string | null;
  next_step_note: string;
  created_at: string;
  first_action_at: string | null;
  items_count?: number;
  items_total?: number;
  utm_source?: string;
  utm_campaign?: string;
  is_key?: boolean;
  counterparty_id?: number | null;
  customer_kind?: string;
  revived_from_id?: number | null;
  routed_at?: string | null;
  converted_at?: string | null;
  attempt_count?: number;
  callback_at?: string | null;
  last_touch_at?: string | null;
  snooze_until?: string | null;
}

function mapLead(l: ApiLead): Lead {
  return {
    id: l.id,
    source: l.source,
    name: l.name,
    company: l.company,
    phone: l.phone ?? undefined,
    email: l.email ?? undefined,
    region: l.region,
    product: l.product,
    message: l.message,
    status: l.status as LeadStatus,
    score: l.score,
    qualification: l.qualification,
    reason: l.reason,
    assignedTo: l.assigned_to,
    funnel: l.funnel,
    dealId: l.deal_id ?? undefined,
    rejectReason: l.reject_reason,
    nextStepAt: l.next_step_at,
    nextStepNote: l.next_step_note,
    createdAt: l.created_at,
    firstActionAt: l.first_action_at,
    itemsCount: l.items_count ?? 0,
    itemsTotal: l.items_total ?? 0,
    utmSource: l.utm_source,
    utmCampaign: l.utm_campaign,
    isKey: l.is_key ?? false,
    counterpartyId: l.counterparty_id ?? undefined,
    customerKind: l.customer_kind ?? "",
    revivedFromId: l.revived_from_id ?? undefined,
    routedAt: l.routed_at ?? null,
    convertedAt: l.converted_at ?? null,
    attemptCount: l.attempt_count ?? 0,
    callbackAt: l.callback_at ?? null,
    lastTouchAt: l.last_touch_at ?? null,
    snoozeUntil: l.snooze_until ?? null,
  };
}

/** Недозвон (Цикл 15): +1 попытка контакта; callbackAt — срок перезвона (без него бэк
 *  ставит «через 2 часа»). Возвращает обновлённый лид или null при ошибке/409. */
export async function logLeadAttempt(id: number, callbackAt?: string): Promise<Lead | null> {
  try {
    const init: RequestInit = { method: "POST" };
    if (callbackAt) {
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify({ callback_at: localToNaiveUtc(callbackAt) });
    }
    const res = await fetch(`/api/leads/${id}/attempt`, init);
    if (!res.ok) return null;
    return mapLead((await res.json()) as ApiLead);
  } catch {
    return null;
  }
}

/** Лиды на приёме (вход воронки) из API (SSR); fallback — пусто. */
export async function fetchLeads(roles?: string): Promise<Lead[]> {
  try {
    const res = await fetch(`${BASE}/leads`, { cache: "no-store", headers: roleHeaders(roles) });
    if (!res.ok) throw new Error(String(res.status));
    return ((await res.json()) as ApiLead[]).map(mapLead);
  } catch {
    return [];
  }
}

/** Один лид по id (SSR, кокпит /crm/leads/[id]) — точечный GET вместо «скачать все и найти».
 *  null — не найден/сбой. Заодно будит созревший «не сейчас» (wake-on-read на бэке). */
export async function fetchLead(id: number, roles?: string): Promise<Lead | null> {
  try {
    const res = await fetch(`${BASE}/leads/${id}`, { cache: "no-store", headers: roleHeaders(roles) });
    if (!res.ok) return null;
    return mapLead((await res.json()) as ApiLead);
  } catch {
    return null;
  }
}

/** Лиды из API (клиент, через /api) — для обновления приёма после входящих заявок.
 *  null (не пустой массив!) при сетевой ошибке/не-2xx — чтобы вызывающий поллинг НЕ
 *  подменял живую доску пустотой при разовом сбое сети (пустой [] = реально нет лидов). */
export async function fetchLeadsClient(): Promise<Lead[] | null> {
  try {
    const res = await fetch("/api/leads", { cache: "no-store" });
    if (!res.ok) throw new Error(String(res.status));
    return ((await res.json()) as ApiLead[]).map(mapLead);
  } catch {
    return null;
  }
}

/** Заявка с сайта (контакт-форма) → публичный коннектор приёма лидов. */
export async function submitWebLead(payload: Record<string, string>): Promise<boolean> {
  return postCall("/api/integrations/web/lead", payload);
}

/** Входящее письмо (вебхук форвардера) → публичный коннектор приёма лидов. */
export async function submitEmailLead(payload: Record<string, string>): Promise<boolean> {
  return postCall("/api/integrations/email/inbound", payload);
}

export interface LeadInput {
  source: string;
  name?: string;
  company?: string;
  phone?: string;
  email?: string;
  region?: string;
  product?: string;
  message?: string;
}

/** Дубль по телефону/e-mail (409 от POST /leads) — уже есть открытый лид с этим контактом. */
export class LeadDuplicateError extends Error {
  constructor(public duplicateOf: number) {
    super(`Дубль лида #${duplicateOf}`);
  }
}

/** Принять лид из канала (клиент, через /api). Кидает LeadDuplicateError на 409-дубль. */
export async function createLead(input: LeadInput): Promise<Lead | null> {
  let res: Response;
  try {
    res = await fetch("/api/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
  } catch {
    return null;
  }
  if (res.status === 409) {
    const body = (await res.json().catch(() => ({}))) as { detail?: { duplicate_of?: number } };
    throw new LeadDuplicateError(body.detail?.duplicate_of ?? 0);
  }
  if (!res.ok) return null;
  return mapLead((await res.json()) as ApiLead);
}

export interface LeadQualifyResult {
  id: number;
  status: LeadStatus;
  score: number;
  qualification: string;
  reason: string;
  ai_rationale: string | null;
  model: string | null;
}

/** Квалифицировать лид (Lead Qualifier): балл + вердикт (+ AI-обоснование, если включён). */
export async function qualifyLead(id: number): Promise<LeadQualifyResult | null> {
  try {
    const res = await fetch(`/api/leads/${id}/qualify`, { method: "POST" });
    if (!res.ok) return null;
    return (await res.json()) as LeadQualifyResult;
  } catch {
    return null;
  }
}

export interface LeadRouteResult {
  id: number;
  status: LeadStatus;
  assigned_to: string;
  funnel: string;
  rationale?: string; // Цикл 8: почему этот менеджер (конверсия/загрузка или ручной выбор)
}

/** Распределить лид на менеджера по правилам (география/продукт/нагрузка/воронка).
 *  `opts.assignedTo` — лид уходит именно этому менеджеру (ручной выбор), без него —
 *  прежнее авто-распределение по правилам. `opts.nextStepAt`/`opts.nextStepNote` —
 *  опционально сохраняются на лиде вместе с раздачей (работает и в авто-, и в ручном режиме). */
/** Локальное naive-время (пресеты/`datetime-local`) → naive-UTC строка бэкенда.
 *  Бэк хранит метки в наивном UTC; без конвертации «завтра 10:00» отображался бы
 *  чипом шага как 13:00 (Минск = UTC+3). Уже-UTC строки (с Z) только чистим от Z. */
export function localToNaiveUtc(local: string): string {
  if (!local) return local;
  if (local.endsWith("Z")) return local.slice(0, -1);
  const d = new Date(local);
  if (Number.isNaN(d.getTime())) return local;
  return d.toISOString().slice(0, 19);
}

export async function routeLead(
  id: number,
  opts?: { assignedTo?: string; nextStepAt?: string; nextStepNote?: string },
): Promise<LeadRouteResult | null> {
  try {
    const init: RequestInit = { method: "POST" };
    const body: Record<string, string> = {};
    if (opts?.assignedTo) body.assigned_to = opts.assignedTo;
    if (opts?.nextStepAt) body.next_step_at = localToNaiveUtc(opts.nextStepAt);
    if (opts?.nextStepNote) body.next_step_note = opts.nextStepNote;
    if (Object.keys(body).length > 0) {
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify(body);
    }
    const res = await fetch(`/api/leads/${id}/route`, init);
    if (!res.ok) return null;
    return (await res.json()) as LeadRouteResult;
  } catch {
    return null;
  }
}

/** Экспресс-передача лида (Цикл 2): квалификация + раздача + следующий шаг одним вызовом.
 *  `opts` — как у routeLead (assignedTo/nextStepAt/nextStepNote), все опциональны.
 *  Бэк вернёт 422, если пересчитанный балл оказался нецелевым (detail — текст для UI),
 *  409 — если лид не в new/qualified. */
export async function expressLead(
  id: number,
  opts?: { assignedTo?: string; nextStepAt?: string; nextStepNote?: string },
): Promise<Lead | { error: string } | null> {
  try {
    const init: RequestInit = { method: "POST" };
    const body: Record<string, string> = {};
    if (opts?.assignedTo) body.assigned_to = opts.assignedTo;
    if (opts?.nextStepAt) body.next_step_at = localToNaiveUtc(opts.nextStepAt);
    if (opts?.nextStepNote) body.next_step_note = opts.nextStepNote;
    if (Object.keys(body).length > 0) {
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify(body);
    }
    const res = await fetch(`/api/leads/${id}/express`, init);
    if (res.status === 422) {
      const err = (await res.json().catch(() => ({}))) as { detail?: string };
      return { error: err.detail ?? "Экспресс недоступен" };
    }
    if (!res.ok) return null;
    return mapLead((await res.json()) as ApiLead);
  } catch {
    return null;
  }
}

/** Отклонить лид (терминальный статус, как converted). Причина — одна из REJECT_REASONS
 *  (иначе бэк вернёт 422). 409, если лид уже converted/rejected. Для «не сейчас» (Цикл 16)
 *  snoozeDays задаёт дату авто-возврата в «Новые» (без него бэк ставит 90 дней). */
export async function rejectLead(
  id: number,
  reason: string,
  snoozeDays?: number,
): Promise<{ id: number; status: LeadStatus; reject_reason: string } | null> {
  try {
    const res = await fetch(`/api/leads/${id}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(snoozeDays ? { reason, snooze_days: snoozeDays } : { reason }),
    });
    if (!res.ok) return null;
    return (await res.json()) as { id: number; status: LeadStatus; reject_reason: string };
  } catch {
    return null;
  }
}

/** Список менеджеров для ручного выбора при раздаче лида (регионы/продукты/текущая загрузка). */
export async function fetchLeadManagers(): Promise<Manager[]> {
  try {
    const res = await fetch(`/api/leads/managers`, { cache: "no-store" });
    if (!res.ok) return [];
    return (await res.json()) as Manager[];
  } catch {
    return [];
  }
}

interface ApiLeadSourceStat {
  source: string;
  utm_campaign: string;
  total: number;
  target: number;
  converted: number;
  rejected: number;
  avg_score: number;
  target_pct: number;
  conversion_pct: number;
  pipeline: number;
}

/** Результат привязки контакта к компании (Цикл 11): POST /leads/{id}/link-contact. */
export interface LinkContactResult {
  contactId: number;
  counterpartyId: number;
  created: boolean; // true — контакт создан; false — уже был в компании
  fullName: string;
}

/** Добавить контакт лида в существующую компанию без дублей (Цикл 11).
 *  Возвращает результат, {error} при 4xx или null при сбое. */
export async function linkLeadContact(
  leadId: number,
  opts?: { counterpartyId?: number; fullName?: string; phone?: string; email?: string; isPrimary?: boolean },
): Promise<LinkContactResult | { error: string } | null> {
  try {
    const res = await fetch(`/api/leads/${leadId}/link-contact`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        counterparty_id: opts?.counterpartyId,
        full_name: opts?.fullName ?? "",
        phone: opts?.phone,
        email: opts?.email,
        is_primary: opts?.isPrimary ?? false,
      }),
    });
    if (!res.ok) {
      const body = (await res.json().catch(() => null)) as { detail?: string } | null;
      return { error: body?.detail ?? "Не удалось добавить контакт" };
    }
    const b = (await res.json()) as {
      contact_id: number;
      counterparty_id: number;
      created: boolean;
      full_name: string;
    };
    return { contactId: b.contact_id, counterpartyId: b.counterparty_id, created: b.created, fullName: b.full_name };
  } catch {
    return null;
  }
}

/** Отчёт качества источников/кампаний (Цикл 4): GET /leads/stats/sources — лениво, при открытии панели. */
export async function fetchLeadSourceStats(days?: number): Promise<LeadSourceStat[]> {
  try {
    const qs = days ? `?days=${days}` : "";
    const res = await fetch(`/api/leads/stats/sources${qs}`, { cache: "no-store" });
    if (!res.ok) return [];
    return ((await res.json()) as ApiLeadSourceStat[]).map((s) => ({
      source: s.source,
      utmCampaign: s.utm_campaign,
      total: s.total,
      target: s.target,
      converted: s.converted,
      rejected: s.rejected,
      avgScore: s.avg_score,
      targetPct: s.target_pct,
      conversionPct: s.conversion_pct,
      pipeline: s.pipeline ?? 0,
    }));
  } catch {
    return [];
  }
}

interface ApiLeadHandoffStat {
  manager: string;
  assigned: number;
  converted: number;
  pipeline: number;
  conversion_pct: number;
  pending?: number;
  pending_pipeline?: number;
  stale?: number;
}

/** Скорборд передач лидоруба продавцам (Цикл 7): GET /leads/stats/handoffs — лениво. */
export async function fetchLeadHandoffStats(days?: number): Promise<LeadHandoffStat[]> {
  try {
    const qs = days ? `?days=${days}` : "";
    const res = await fetch(`/api/leads/stats/handoffs${qs}`, { cache: "no-store" });
    if (!res.ok) return [];
    return ((await res.json()) as ApiLeadHandoffStat[]).map((s) => ({
      manager: s.manager,
      assigned: s.assigned,
      converted: s.converted,
      pipeline: s.pipeline,
      conversionPct: s.conversion_pct,
      pending: s.pending ?? 0,
      pendingPipeline: s.pending_pipeline ?? 0,
      stale: s.stale ?? 0,
    }));
  } catch {
    return [];
  }
}

interface ApiLeadPlan {
  leads_target: number;
  qualified_target: number;
  converted_target: number;
  reaction_target_min: number;
  leads_fact: number;
  qualified_fact: number;
  converted_fact: number;
  reaction_fact_min: number | null;
}

function mapLeadPlan(p: ApiLeadPlan): LeadPlan {
  return {
    leadsTarget: p.leads_target,
    qualifiedTarget: p.qualified_target,
    convertedTarget: p.converted_target,
    reactionTargetMin: p.reaction_target_min,
    leadsFact: p.leads_fact,
    qualifiedFact: p.qualified_fact,
    convertedFact: p.converted_fact,
    reactionFactMin: p.reaction_fact_min,
  };
}

/** Результат «Разобрать целевых» (Цикл 6): POST /leads/express-bulk. */
export interface LeadBulkExpressResult {
  expressed: number[]; // id распределённых лидов
  skippedNonTarget: number; // нецелевые новые лиды — пропущены (разбирают вручную)
}

/** Разобрать все целевые новые лиды одним действием (Цикл 6). null — при сбое API. */
export async function expressBulkLeads(): Promise<LeadBulkExpressResult | null> {
  try {
    const res = await fetch(`/api/leads/express-bulk`, { method: "POST" });
    if (!res.ok) return null;
    const body = (await res.json()) as { expressed: number[]; skipped_non_target: number };
    return { expressed: body.expressed, skippedNonTarget: body.skipped_non_target };
  } catch {
    return null;
  }
}

/** План/факт лидоруба за сегодня (Цикл 5): GET /leads/plan. null — если API недоступен. */
export async function fetchLeadPlan(): Promise<LeadPlan | null> {
  try {
    const res = await fetch(`/api/leads/plan`, { cache: "no-store" });
    if (!res.ok) return null;
    return mapLeadPlan((await res.json()) as ApiLeadPlan);
  } catch {
    return null;
  }
}

/** Задать дневную норму лидоруба (Цикл 5): PUT /leads/plan → обновлённый план/факт. */
export async function saveLeadPlan(targets: {
  leadsTarget: number;
  qualifiedTarget: number;
  convertedTarget: number;
  reactionTargetMin: number;
}): Promise<LeadPlan | null> {
  try {
    const res = await fetch(`/api/leads/plan`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        leads_target: targets.leadsTarget,
        qualified_target: targets.qualifiedTarget,
        converted_target: targets.convertedTarget,
        reaction_target_min: targets.reactionTargetMin,
      }),
    });
    if (!res.ok) return null;
    return mapLeadPlan((await res.json()) as ApiLeadPlan);
  } catch {
    return null;
  }
}

export interface LeadConvertResult {
  lead_id: number;
  status: LeadStatus;
  /** id созданной сделки. Появляется не сразу: sales создаёт сделку асинхронно по
   *  событию `leads.lead.converted` (§2.4), здесь мы её дожидаемся поллингом. */
  deal_id?: number;
}

/** Дождаться, пока relay проставит лиду `deal_id` (сделку создаёт sales по событию). */
async function pollLeadDealId(id: number, tries = 12): Promise<number | undefined> {
  for (let i = 0; i < tries; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    try {
      const res = await fetch(`/api/leads/${id}`, { cache: "no-store" });
      if (res.ok) {
        const dealId = ((await res.json()) as ApiLead).deal_id;
        if (dealId) return dealId;
      }
    } catch {
      // сеть моргнула — пробуем следующий тик
    }
  }
  return undefined;
}

/** Конвертировать распределённый лид. Сам convert лишь помечает лид и публикует
 *  `leads.lead.converted`; сделку создаёт модуль sales (§2.4) — её id подтягиваем
 *  поллингом, чтобы вернуть UI готовую ссылку «Открыть сделку». */
export async function convertLead(id: number): Promise<LeadConvertResult | null> {
  try {
    const res = await fetch(`/api/leads/${id}/convert`, { method: "POST" });
    if (!res.ok) return null;
    const conv = (await res.json()) as { lead_id: number; status: LeadStatus };
    return { ...conv, deal_id: await pollLeadDealId(id) };
  } catch {
    return null;
  }
}

/** Позиция подобранного КП на лиде (Цикл 3): корзина каталог-пикера, сохранённая на лиде. */
export interface LeadCartItem {
  skuId: number;
  skuCode: string;
  name: string;
  qty: number;
  price: number; // цена клиенту (уже со скидкой), BYN
  discountPct: number;
}

interface ApiLeadItem {
  id: number;
  lead_id: number;
  sku_id: number;
  sku_code: string;
  name: string;
  qty: number;
  price: number;
  discount_pct: number;
  created_at: string;
}

function mapLeadItem(it: ApiLeadItem): LeadCartItem {
  return {
    skuId: it.sku_id,
    skuCode: it.sku_code,
    name: it.name,
    qty: it.qty,
    price: it.price,
    discountPct: it.discount_pct,
  };
}

/** Подобранный КП лида (позиции каталог-пикера). */
export async function fetchLeadItems(leadId: number): Promise<LeadCartItem[]> {
  try {
    const res = await fetch(`/api/leads/${leadId}/items`, { cache: "no-store" });
    if (!res.ok) return [];
    return ((await res.json()) as ApiLeadItem[]).map(mapLeadItem);
  } catch {
    return [];
  }
}

/** Заменить весь подбор лида (replace-all — весь список корзины пикера целиком). */
export async function saveLeadItems(leadId: number, items: LeadCartItem[]): Promise<boolean> {
  try {
    const res = await fetch(`/api/leads/${leadId}/items`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(
        items.map((it) => ({
          sku_id: it.skuId,
          sku_code: it.skuCode,
          name: it.name,
          qty: it.qty,
          price: it.price,
          discount_pct: it.discountPct,
        })),
      ),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Перенести подбор лида в созданную сделку: позиции (addDealItem) + цена клиенту
 * (createPriceQuote) — тот же контракт, что и `commitToDeal` пикера, но от сохранённых
 * позиций лида (без открытого пикера). Котировки ждём (await), чтобы рендер счёта
 * не прочитал ещё не записанные цены. */
export async function commitLeadItemsToDeal(
  dealId: string,
  counterparty: string,
  items: LeadCartItem[],
): Promise<{ ok: number; total: number }> {
  const results = await Promise.all(items.map((it) => addDealItem(dealId, it.skuId, it.qty)));
  await Promise.all(
    items.map((it) => (it.price ? createPriceQuote(it.skuCode, counterparty, it.price) : Promise.resolve(true))),
  );
  return { ok: results.filter(Boolean).length, total: items.length };
}

function mapAttachment(raw: {
  id: number;
  lead_id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  source: string;
  created_at: string;
}): LeadAttachment {
  return {
    id: raw.id,
    leadId: raw.lead_id,
    filename: raw.filename,
    contentType: raw.content_type,
    sizeBytes: raw.size_bytes,
    source: raw.source,
    createdAt: raw.created_at,
  };
}

/** Вложения лида (сканы тендерных заявок/писем/ручная загрузка). */
export async function fetchLeadAttachments(leadId: number): Promise<LeadAttachment[]> {
  try {
    const res = await fetch(`/api/leads/${leadId}/attachments`, { cache: "no-store" });
    if (!res.ok) return [];
    return ((await res.json()) as Parameters<typeof mapAttachment>[0][]).map(mapAttachment);
  } catch {
    return [];
  }
}

export interface UploadAttachmentResult {
  attachment?: LeadAttachment;
  error?: string; // detail из 422 или общая ошибка сети
}

/** Загрузить файл вложения: читаем как data-URI на клиенте (сервер multipart не парсит —
 *  тот же паттерн, что у логотипа продавца в sales), шлём JSON. */
export async function uploadLeadAttachment(
  leadId: number,
  file: File,
  source: string = "manual",
): Promise<UploadAttachmentResult> {
  try {
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(file);
    });
    const res = await fetch(`/api/leads/${leadId}/attachments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: file.name, data_url: dataUrl, source }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      return { error: body?.detail ?? "Не удалось загрузить файл" };
    }
    return { attachment: mapAttachment(await res.json()) };
  } catch {
    return { error: "Не удалось загрузить файл" };
  }
}

/** Прямая ссылка на скачивание/просмотр вложения — content-type решает браузер. */
export function leadAttachmentDownloadUrl(leadId: number, attachmentId: number): string {
  return `/api/leads/${leadId}/attachments/${attachmentId}/download`;
}

/** Удалить вложение лида (ошибочно загруженный файл с ПДн). true — удалено (204/404). */
export async function deleteLeadAttachment(leadId: number, attachmentId: number): Promise<boolean> {
  try {
    const res = await fetch(`/api/leads/${leadId}/attachments/${attachmentId}`, { method: "DELETE" });
    return res.ok || res.status === 404; // 404 — уже нет, цель достигнута
  } catch {
    return false;
  }
}

export interface OwnerMetrics {
  approvals_pending: number;
  approvals_total: number;
  audit_count: number;
  events_count: number;
  counterparties: number;
  skus: number;
  modules: string[];
  widgets: { key: string; title: string }[];
}

export interface OwnerDashboard {
  metrics: OwnerMetrics;
  stages: Stage[];
  kpis: Kpi[];
}

/** AI-инсайт по здоровью бизнеса (AI Control Tower). null — AI выключен / ошибка. */
export async function fetchOwnerInsight(): Promise<string | null> {
  try {
    const res = await fetch("/api/system/owner/insight", { cache: "no-store" });
    if (!res.ok) return null;
    return ((await res.json()) as { text: string }).text;
  } catch {
    return null;
  }
}

/** Панель владельца (Control Tower): кросс-модульные метрики + воронка + KPI (SSR). */
export async function fetchOwnerDashboard(roles?: string): Promise<OwnerDashboard | null> {
  try {
    const [metricsRes, stages, kpis] = await Promise.all([
      fetch(`${BASE}/system/owner`, { cache: "no-store", headers: roleHeaders(roles) }),
      fetchBoardStages(roles),
      fetchKpis(roles),
    ]);
    if (!metricsRes.ok) throw new Error(String(metricsRes.status));
    const metrics = (await metricsRes.json()) as OwnerMetrics;
    return { metrics, stages, kpis };
  } catch {
    return null;
  }
}

/** Лого продавца для печатных форм (счёт/договор) — honest null, если не загружено. */
export async function fetchBranding(): Promise<string | null> {
  try {
    const res = await fetch("/api/sales/branding", { cache: "no-store" });
    if (!res.ok) return null;
    return ((await res.json()) as { logo_data_url: string | null }).logo_data_url;
  } catch {
    return null;
  }
}

/** Загрузить/заменить лого. ``logoDataUrl`` — data-URI, собирается на клиенте (FileReader). */
export async function updateBranding(logoDataUrl: string): Promise<boolean> {
  try {
    const res = await fetch("/api/sales/branding", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ logo_data_url: logoDataUrl }),
    });
    return res.ok;
  } catch {
    return false;
  }
}
