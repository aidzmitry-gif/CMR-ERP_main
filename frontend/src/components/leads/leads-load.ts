import type { Lead, LeadStatus } from "@/lib/types";

/** Результат загрузки лидов: ok / auth (401|403) / error — не смешиваем с «лидов нет». */
export type LeadsLoadState = "ok" | "auth" | "error";

export interface LeadsLoadResult {
  state: LeadsLoadState;
  leads: Lead[];
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

function classifyResponse(res: Response): LeadsLoadState {
  if (res.status === 401 || res.status === 403) return "auth";
  if (!res.ok) return "error";
  return "ok";
}

const SSR_BASE = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

/** SSR: GET /leads с явным разбором 403 (не маскируем под пустой инбокс). */
export async function loadLeadsServer(role: string, accessToken?: string): Promise<LeadsLoadResult> {
  try {
    const headers: Record<string, string> = { "X-User-Roles": role };
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    const res = await fetch(`${SSR_BASE}/leads`, { cache: "no-store", headers });
    const state = classifyResponse(res);
    if (state !== "ok") return { state, leads: [] };
    const leads = ((await res.json()) as ApiLead[]).map(mapLead);
    return { state: "ok", leads };
  } catch {
    return { state: "error", leads: [] };
  }
}

/** Клиент: GET /api/leads через прокси Next (поллинг приёма). */
export async function loadLeadsClient(): Promise<LeadsLoadResult> {
  try {
    const res = await fetch("/api/leads", { cache: "no-store" });
    const state = classifyResponse(res);
    if (state !== "ok") return { state, leads: [] };
    const leads = ((await res.json()) as ApiLead[]).map(mapLead);
    return { state: "ok", leads };
  } catch {
    return { state: "error", leads: [] };
  }
}
