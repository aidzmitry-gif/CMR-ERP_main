import { DEAL_DETAIL, getDealDetail, KPIS, STAGES } from "@/lib/mock-data";
import type { Deal, DealDetail, Kpi, KpiIcon, KpiTone, Priority, Stage } from "@/lib/types";

// Базовый URL бэкенда для серверных компонентов (SSR-fetch).
const BASE = process.env.BACKEND_URL ?? "http://localhost:8000";

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
    amount: d.amount,
    priority: d.priority as Priority,
    owner: d.owner,
    date: d.deal_date ?? undefined,
    closedDate: d.closed_date ?? undefined,
    nextStep: d.next_step ?? undefined,
    starred: d.starred,
  };
}

/** Доска сделок из API; при недоступности бэкенда — fallback на mock. */
export async function fetchBoardStages(): Promise<Stage[]> {
  try {
    const res = await fetch(`${BASE}/sales/board`, { cache: "no-store" });
    if (!res.ok) throw new Error(String(res.status));
    const data = (await res.json()) as { stages: ApiStage[] };
    return data.stages.map((s) => ({
      id: s.id,
      title: s.title,
      color: s.color,
      count: s.count,
      sum: s.sum,
      deals: s.deals.map(mapDeal),
    }));
  } catch {
    return STAGES;
  }
}

/** Детальная карточка сделки из API; fallback — mock по id. */
export async function fetchDealDetail(id: string): Promise<DealDetail> {
  try {
    const res = await fetch(`${BASE}/sales/deals/${id}`, { cache: "no-store" });
    if (!res.ok) throw new Error(String(res.status));
    const d = (await res.json()) as ApiDeal & {
      items?: { title: string; last_price: number | null; min_price: number | null }[];
    };
    return {
      number: d.number,
      company: d.counterparty,
      description: d.title,
      amount: d.amount,
      priority: d.priority as Priority,
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
export async function fetchKpis(): Promise<Kpi[]> {
  try {
    const res = await fetch(`${BASE}/sales/kpis`, { cache: "no-store" });
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
export async function fetchOwnerDashboard(): Promise<OwnerDashboard | null> {
  try {
    const [metricsRes, stages, kpis] = await Promise.all([
      fetch(`${BASE}/system/owner`, { cache: "no-store" }),
      fetchBoardStages(),
      fetchKpis(),
    ]);
    if (!metricsRes.ok) throw new Error(String(metricsRes.status));
    const metrics = (await metricsRes.json()) as OwnerMetrics;
    return { metrics, stages, kpis };
  } catch {
    return null;
  }
}
