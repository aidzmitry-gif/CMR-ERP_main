import type { Stage } from "@/lib/types";

/** Пересчитать count/sum каждой стадии по её сделкам (после перемещений). */
export function recomputeStages(stages: Stage[]): Stage[] {
  return stages.map((s) => ({
    ...s,
    count: s.deals.length,
    sum: s.deals.reduce((acc, d) => acc + d.amount, 0),
  }));
}

/** Переместить сделку в целевую стадию (drag&drop).
 *
 * Возвращает прежний массив без изменений, если сделка не найдена или уже в
 * целевой стадии; иначе — новый массив стадий с пересчитанными агрегатами.
 */
export function moveDealToStage(stages: Stage[], dealId: string, targetStage: string): Stage[] {
  const source = stages.find((s) => s.deals.some((d) => d.id === dealId));
  if (!source || source.id === targetStage) return stages;
  const deal = source.deals.find((d) => d.id === dealId);
  if (!deal) return stages;
  const next = stages.map((s) => {
    if (s.id === source.id) return { ...s, deals: s.deals.filter((d) => d.id !== dealId) };
    if (s.id === targetStage) return { ...s, deals: [...s.deals, deal] };
    return s;
  });
  return recomputeStages(next);
}
