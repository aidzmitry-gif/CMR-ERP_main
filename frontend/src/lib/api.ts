import { DEAL_DETAIL, getDealDetail, STAGES } from "@/lib/mock-data";
import type { Deal, DealDetail, Priority, Stage } from "@/lib/types";

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
    const d = (await res.json()) as ApiDeal;
    return {
      number: d.number,
      company: d.counterparty,
      description: d.title,
      amount: d.amount,
      priority: d.priority as Priority,
      nextStep: d.next_step ?? DEAL_DETAIL.nextStep,
      contact: d.owner || DEAL_DETAIL.contact,
      datetime: `${d.deal_date ?? d.closed_date ?? ""} • 14:00`,
      // позиции номенклатуры и сообщения пока демонстрационные
      itemsTitle: DEAL_DETAIL.itemsTitle,
      items: DEAL_DETAIL.items,
      messages: DEAL_DETAIL.messages,
    };
  } catch {
    return getDealDetail(id);
  }
}
