// Клиентские вызовы единого экрана планирования (/crm/deals/planning). Вынесены из api.ts
// отдельным файлом — api.ts периодически держит параллельная полоса, общий файл конфликтует
// (тот же приём, что contracts-api.ts). Ходят через тот же /api-прокси, что и остальные
// клиентские вызовы: прокси пробрасывает роль из cookie и статус/тело ответа как есть.
import type { Kpi } from "./types";

/**
 * Вернуть согласованный план в работу: approved → draft (POST /plans/{id}/reopen).
 * Один путь для двух кнопок:
 *  - продавец «↻ Пересмотр» — снять согласование, поправить цифру в конструкторе и переотправить;
 *  - РОП «Вернуть на доработку» — с причиной (уходит в rop_comment плана).
 * 409, если план не в статусе approved. reason опционален (для «Пересмотра» его нет).
 */
export async function reopenPlan(id: number, reason?: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/sales/plans/${id}/reopen`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(reason ? { reason } : {}),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * Решение РОПа по метрике с комментарием (POST /plans/{id}/decide). comment (если задан)
 * пишется в plan.rop_comment — и при согласовании, и при отклонении; логика статусов
 * не меняется (approve → approved, reject → rejected).
 */
export async function decidePlanComment(
  id: number,
  approved: boolean,
  comment?: string,
): Promise<boolean> {
  try {
    const res = await fetch(`/api/sales/plans/${id}/decide`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved, comment: comment?.trim() || undefined }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Сырой KPI бэка (форма /sales/kpis) — приватная, как в api.ts. */
interface RawKpi {
  key: string;
  title: string;
  target: number;
  actual: number;
  percent: number;
  unit: string;
  icon: string;
  tone: string;
}

/**
 * KPI за период С учётом согласованного плана владельца: /sales/kpis?period=&owner_id=.
 * Когда у владельца есть согласованный PlanTarget за текущий месяц — бэк отдаёт «План»
 * денег-метрик из него (с добором до годовой), а не KpiTarget×множитель. Маппинг тот же,
 * что getKpis в api.ts (форму дублируем, чтобы не трогать api.ts — общий хотспот).
 */
export async function getKpisForOwner(period: string, ownerId: number): Promise<Kpi[]> {
  try {
    const qs = new URLSearchParams({ period, owner_id: String(ownerId) });
    const res = await fetch(`/api/sales/kpis?${qs.toString()}`, { cache: "no-store" });
    if (!res.ok) throw new Error(String(res.status));
    return ((await res.json()) as RawKpi[]).map((k) => ({
      id: k.key,
      label: k.title,
      value: k.actual,
      target: k.target,
      percent: k.percent,
      money: k.unit === "money",
      icon: k.icon as Kpi["icon"],
      tone: k.tone as Kpi["tone"],
    }));
  } catch {
    return [];
  }
}
