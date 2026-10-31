import { businessDate } from "@/lib/business-date";
import { SALES_STAGES, STAGE_BY_ID, TERMINAL_STAGES } from "@/lib/sales-stages";

/** Read-only fields of native DealRead. Amount has no currency and is not revenue. */
export interface RopDeal {
  id: number;
  number: string;
  title: string;
  counterparty: string;
  stage: string;
  owner: string;
  owner_id: number | null;
  next_step: string | null;
  next_step_at: string | null;
  expected_close_date: string | null;
  probability: number | null;
}

export function readRopDeals(value: unknown): RopDeal[] {
  if (!Array.isArray(value)) throw new Error("Invalid deal list");
  const ids = new Set<number>();
  for (const row of value) {
    if (!row || typeof row !== "object" ||
        !Number.isSafeInteger(row.id) || row.id <= 0 || ids.has(row.id) ||
        !["number", "title", "counterparty", "stage", "owner"].every(key => typeof row[key] === "string") ||
        !row.stage.trim() ||
        !(row.owner_id === null || (Number.isSafeInteger(row.owner_id) && row.owner_id > 0)) ||
        !["next_step", "next_step_at", "expected_close_date"].every(key => row[key] === null || typeof row[key] === "string") ||
        !(row.probability === null || (Number.isInteger(row.probability) && row.probability >= 0 && row.probability <= 100))) {
      throw new Error("Invalid deal row");
    }
    ids.add(row.id);
  }
  return value as RopDeal[];
}

function validCalendar(iso: string): boolean {
  const date = new Date(`${iso}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === iso;
}

/** Backend calendar field uses dd.mm.yyyy, not the browser's date parser. */
function closeDate(value: string | null): string | null {
  const match = value?.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
  if (!match) return null;
  const iso = `${match[3]}-${match[2]}-${match[1]}`;
  return validCalendar(iso) ? iso : null;
}

/** Naive backend timestamps are UTC, matching api.ts / localToNaiveUtc. */
export function ropStepTime(value: string | null): number | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)?$/i.test(value) ||
      !validCalendar(value.slice(0, 10))) return null;
  const stamp = Date.parse(/(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`);
  return Number.isFinite(stamp) ? stamp : null;
}

export interface RopAttention {
  deal: RopDeal;
  overdue: boolean;
  missingStep: boolean;
  lateClose: boolean;
  invalidDate: boolean;
  reasons: string[];
}

export function ropSnapshot(deals: RopDeal[], now: Date) {
  const today = businessDate(now);
  const counts = new Map<string, number>();
  const owners = new Map<number | null, { ownerId: number | null; name: string; labels: Set<string>; total: number; open: number; attention: number }>();
  const attention: RopAttention[] = [];
  let open = 0, won = 0, lost = 0, unknown = 0, withoutProbability = 0;
  for (const deal of deals) {
    counts.set(deal.stage, (counts.get(deal.stage) ?? 0) + 1);
    const known = Object.hasOwn(STAGE_BY_ID, deal.stage);
    const active = known && !TERMINAL_STAGES.has(deal.stage);
    if (!known) unknown++;
    if (active) open++;
    if (deal.stage === "won") won++;
    if (deal.stage === "lost") lost++;
    if (active && deal.probability === null) withoutProbability++;

    const nextTime = ropStepTime(deal.next_step_at);
    const closing = closeDate(deal.expected_close_date);
    const item: RopAttention = {
      deal,
      overdue: active && nextTime !== null && nextTime < now.getTime(),
      missingStep: active && (!deal.next_step?.trim() || !deal.next_step_at),
      lateClose: active && closing !== null && closing < today,
      invalidDate: active && ((Boolean(deal.next_step_at) && nextTime === null) || (Boolean(deal.expected_close_date) && closing === null)),
      reasons: [],
    };
    if (item.overdue) item.reasons.push("Следующий шаг просрочен");
    if (item.missingStep) item.reasons.push("Не задан шаг или его срок");
    if (item.lateClose) item.reasons.push("Плановая дата закрытия прошла");
    if (item.invalidDate) item.reasons.push("Проверьте формат даты");
    if (item.reasons.length) attention.push(item);

    const person = owners.get(deal.owner_id) ?? {
      ownerId: deal.owner_id, name: deal.owner.trim() || `Сотрудник #${deal.owner_id}`,
      labels: new Set<string>(), total: 0, open: 0, attention: 0,
    };
    if (deal.owner.trim()) person.labels.add(deal.owner.trim());
    person.total++;
    if (active) person.open++;
    if (item.reasons.length) person.attention++;
    owners.set(deal.owner_id, person);
  }
  attention.sort((a, b) => Number(b.overdue) - Number(a.overdue) ||
    (ropStepTime(a.deal.next_step_at) ?? Infinity) - (ropStepTime(b.deal.next_step_at) ?? Infinity) || a.deal.id - b.deal.id);
  return {
    total: deals.length, open, won, lost, unknown, withoutProbability, attention,
    overdue: attention.filter(item => item.overdue).length,
    missingStep: attention.filter(item => item.missingStep).length,
    lateClose: attention.filter(item => item.lateClose).length,
    invalidDate: attention.filter(item => item.invalidDate).length,
    stages: [
      ...SALES_STAGES.map(stage => ({ id: stage.id, title: stage.title, count: counts.get(stage.id) ?? 0 })),
      ...[...counts].filter(([id]) => !Object.hasOwn(STAGE_BY_ID, id)).map(([id, count]) => ({ id, title: `Неизвестный этап: ${id}`, count })),
    ],
    team: [...owners.values()].sort((a, b) => b.attention - a.attention || b.open - a.open || (a.ownerId ?? Infinity) - (b.ownerId ?? Infinity)),
  };
}
