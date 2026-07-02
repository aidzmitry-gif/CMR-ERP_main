import { daysInStage, ensureLostStage, STUCK_DAYS } from "@/lib/board";
import { progressionIndex, STAGE_BY_ID, TERMINAL_STAGES } from "@/lib/sales-stages";
import { DEAL_DETAIL, getDealDetail, KPIS, STAGES } from "@/lib/mock-data";
import type { Deal, DealDetail, Kpi, KpiIcon, KpiTone, Lead, LeadStatus, LossReason, Priority, Stage } from "@/lib/types";
import { toPriority } from "@/lib/types";

// Базовый URL бэкенда для серверных компонентов (SSR-fetch).
const BASE = process.env.BACKEND_URL ?? "http://localhost:8000";

// SSR-фетчи ходят на BASE напрямую, минуя /api-прокси, поэтому роль надо пробросить
// заголовком вручную (роль читает серверный хелпер `role-server.ts` из cookie). На клиенте
// (вызовы через /api/*) роль добавляет прокси `app/api/[...path]/route.ts`.
function roleHeaders(roles?: string): Record<string, string> | undefined {
  return roles ? { "X-User-Roles": roles } : undefined;
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
    starred: d.starred,
    // Сделки 2.0: вероятность/прогноз (SALES-44), история стадий (SALES-43), причина отказа (SALES-40)
    probability: d.probability ?? undefined,
    expectedCloseDate: d.expected_close_date ?? undefined,
    stageChangedAt: d.stage_changed_at ?? undefined,
    lostReasonCode: d.lost_reason_code ?? undefined,
    lostComment: d.lost_comment ?? undefined,
  };
}

/** Доска сделок из API; при недоступности бэкенда — fallback на mock.
 * В обоих случаях гарантируем колонку «отказ» (SALES-40) через {@link ensureLostStage}. */
export async function fetchBoardStages(roles?: string, funnel?: string): Promise<Stage[]> {
  try {
    const qs = funnel ? `?funnel=${encodeURIComponent(funnel)}` : "";
    const res = await fetch(`${BASE}/sales/board${qs}`, { cache: "no-store", headers: roleHeaders(roles) });
    if (!res.ok) throw new Error(String(res.status));
    const data = (await res.json()) as { stages: ApiStage[] };
    return ensureLostStage(
      data.stages.map((s) => ({
        id: s.id,
        title: s.title,
        color: s.color,
        count: s.count,
        sum: s.sum,
        deals: s.deals.map(mapDeal),
      })),
    );
  } catch {
    return ensureLostStage(STAGES);
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

/** Список воронок sales для переключателя на доске. */
export async function fetchFunnels(): Promise<FunnelRow[]> {
  try {
    const res = await fetch("/api/sales/funnels", { cache: "no-store" });
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
export async function fetchSkus(): Promise<SkuOption[]> {
  try {
    const res = await fetch("/api/sales/skus", { cache: "no-store" });
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
export async function createDocument(dealId: string, kind: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/sales/deals/${dealId}/documents`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, requested_by: "Менеджер" }),
    });
    return res.ok;
  } catch {
    return false;
  }
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
  };
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

/** Лиды из API (клиент, через /api) — для обновления приёма после входящих заявок. */
export async function fetchLeadsClient(): Promise<Lead[]> {
  try {
    const res = await fetch("/api/leads", { cache: "no-store" });
    if (!res.ok) throw new Error(String(res.status));
    return ((await res.json()) as ApiLead[]).map(mapLead);
  } catch {
    return [];
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

/** Принять лид из канала (клиент, через /api). */
export async function createLead(input: LeadInput): Promise<Lead | null> {
  try {
    const res = await fetch("/api/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!res.ok) return null;
    return mapLead((await res.json()) as ApiLead);
  } catch {
    return null;
  }
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
}

/** Распределить лид на менеджера по правилам (география/продукт/нагрузка/воронка). */
export async function routeLead(id: number): Promise<LeadRouteResult | null> {
  try {
    const res = await fetch(`/api/leads/${id}/route`, { method: "POST" });
    if (!res.ok) return null;
    return (await res.json()) as LeadRouteResult;
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
