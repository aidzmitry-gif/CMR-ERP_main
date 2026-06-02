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
    const d = (await res.json()) as ApiDeal & { items?: { title: string }[] };
    return {
      number: d.number,
      company: d.counterparty,
      description: d.title,
      amount: d.amount,
      priority: d.priority as Priority,
      nextStep: d.next_step ?? DEAL_DETAIL.nextStep,
      contact: d.owner || DEAL_DETAIL.contact,
      datetime: `${d.deal_date ?? d.closed_date ?? ""} • 14:00`,
      // позиции номенклатуры — реальные (из связанных SKU); сообщения пока демо
      itemsTitle: "Номенклатура",
      items: (d.items ?? []).map((i) => i.title),
      messages: DEAL_DETAIL.messages,
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

/** KPI «План на сегодня» из API; fallback на mock, если бэкенд/данные недоступны. */
export async function fetchKpis(): Promise<Kpi[]> {
  try {
    const res = await fetch(`${BASE}/sales/kpis`, { cache: "no-store" });
    if (!res.ok) throw new Error(String(res.status));
    const data = (await res.json()) as ApiKpi[];
    if (data.length === 0) return KPIS;
    return data.map((k) => ({
      id: k.key,
      label: k.title,
      value: k.actual,
      target: k.target,
      percent: k.percent,
      money: k.unit === "money",
      icon: k.icon as KpiIcon,
      tone: k.tone as KpiTone,
    }));
  } catch {
    return KPIS;
  }
}
