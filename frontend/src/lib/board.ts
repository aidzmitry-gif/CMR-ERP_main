import type { Deal, LossReason, Stage } from "@/lib/types";
import { LOST_STAGE, STAGE_PROBABILITY } from "@/lib/sales-stages";

// Единый источник стадий — sales-stages.ts (канон, зеркало backend stages.py).
// Реэкспорт сохраняет существующих импортёров `@/lib/board` (SALES-40/44).
export { LOST_STAGE, STAGE_PROBABILITY };

/** Порог «висяка» в днях (SALES-43): дольше — оранжевая подсветка и фильтр «Только висяки». */
export const STUCK_DAYS = 4;

/** Fallback-список причин отказа, когда `/sales/loss-reasons` недоступен (SALES-40).
 * Совпадает с проверенным макетом mockup_Сделки_2.0.html. */
export const LOSS_REASONS: LossReason[] = [
  { code: "price", title: "Дорого / не прошли по цене" },
  { code: "competitor", title: "Ушёл к конкуренту" },
  { code: "no_need", title: "Нет потребности сейчас" },
  { code: "no_answer", title: "Не дозвонились / нет ответа" },
  { code: "timing", title: "Не тот срок поставки" },
  { code: "no_stock", title: "Нет товара на складе" },
  { code: "other", title: "Другое" },
];

const DAY_MS = 86_400_000;

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

/** Гарантировать колонку «отказ» на доске (SALES-40).
 *
 * Бэкенд уже включает стадию `lost`, но при graceful-fallback на mock её нет —
 * добавляем пустую в конец. Идемпотентна: если стадия уже есть, возвращает вход без изменений.
 */
export function ensureLostStage(stages: Stage[]): Stage[] {
  if (stages.some((s) => s.id === LOST_STAGE.id)) return stages;
  return [...stages, { ...LOST_STAGE, count: 0, sum: 0, deals: [] }];
}

/** Эффективная вероятность сделки (SALES-44): явное поле или дефолт по стадии (иначе 0). */
export function probabilityFor(deal: Deal, stageId: string): number {
  return deal.probability ?? STAGE_PROBABILITY[stageId] ?? 0;
}

/** Взвешенная сумма сделки = `amount × probability / 100` (SALES-44). */
export function weightedAmount(deal: Deal, stageId: string): number {
  return (deal.amount * probabilityFor(deal, stageId)) / 100;
}

/** Стадия «в работе» — открытый pipeline (без won/lost/cond_lost). Единый критерий
 *  охвата для взвешенного прогноза: и итог PipelineRow, и «взвешенно» в шапке колонки
 *  считают по нему — иначе Σ колонок ≠ итогу (cond_lost даёт 5% в колонке, но не в итоге). */
export const isOpenStage = (s: Stage): boolean =>
  s.id !== "won" && s.id !== "lost" && s.id !== "cond_lost";

/** Взвешенная сумма стадии — сумма взвешенных сумм её сделок (для шапки колонки). */
export function stageWeightedSum(stage: Stage): number {
  return stage.deals.reduce((acc, d) => acc + weightedAmount(d, stage.id), 0);
}

/** Число полных дней в текущей стадии из `stage_changed_at` (SALES-43).
 * `null`, если дата неизвестна/неразборчива; не уходит в минус для будущей даты. */
export function daysInStage(stageChangedAt: string | undefined, now: number): number | null {
  if (!stageChangedAt) return null;
  const ts = Date.parse(stageChangedAt);
  if (Number.isNaN(ts)) return null;
  return Math.max(0, Math.floor((now - ts) / DAY_MS));
}

/** «Висяк» (SALES-43): открытая сделка без движения по стадии дольше порога.
 * Терминальные стадии (won/lost) висяками не считаются. */
export function isStuck(deal: Deal, stageId: string, now: number, threshold = STUCK_DAYS): boolean {
  if (stageId === "won" || stageId === "lost") return false;
  const days = daysInStage(deal.stageChangedAt, now);
  return days != null && days >= threshold;
}
