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

/** Закрытая стадия по коду: won/lost и производные (cond_lost, rp_won, tn_lost…) —
 * endsWith покрывает и канонические id, и коды стадий секций «Все вместе». */
export function isClosedStageId(stageId: string): boolean {
  return stageId.endsWith("won") || stageId.endsWith("lost");
}

/** «Висяк» (SALES-43): открытая сделка без движения по стадии дольше порога.
 * Закрытые стадии (won/lost, включая cond_lost) висяками не считаются — единый гейт
 * для карточки, списка, счётчика колонки и фильтра; у cond_lost свой сигнал —
 * «реанимировать» ({@link reviveDays}). */
export function isStuck(deal: Deal, stageId: string, now: number, threshold = STUCK_DAYS): boolean {
  if (isClosedStageId(stageId)) return false;
  const days = daysInStage(deal.stageChangedAt, now);
  return days != null && days >= threshold;
}

/** Порог «реанимации» условного отказа: дольше N дней в cond_lost — пора вернуть в работу. */
export const REVIVE_AFTER_DAYS = 7;

/** «Реанимировать» (слайс 3): сделка в «Условном отказе» без касания дольше порога —
 * возвращает дни в стадии для чипа «реанимировать · N дн», иначе null. cond_lost —
 * реанимируемая стадия (sales-stages.ts), для остальных сигнал не имеет смысла. */
export function reviveDays(deal: Deal, stageId: string, now: number): number | null {
  if (!stageId.endsWith("cond_lost")) return null;
  const days = daysInStage(deal.stageChangedAt, now);
  return days != null && days >= REVIVE_AFTER_DAYS ? days : null;
}

/** Бакет вида «По датам действий» (П4, слайс 4) — id колонки для {@link dateBucketId}. */
export type DateBucketId = "overdue" | "today" | "tomorrow" | "week" | "month" | "later" | "no_date";

/** Метаданные колонок группировки «По датам действий» (порядок = порядок мокапа,
 * цвета — как в `sales-board-mockup.html`). «Без даты» — честный отдельный бакет
 * (НЕ подмешивается в «Позже» — сделка без next_step_at это не «когда-то потом», а «неизвестно»). */
export const DATE_BUCKETS: { id: DateBucketId; title: string; color: string }[] = [
  { id: "overdue", title: "Просрочено", color: "#EF4444" },
  { id: "today", title: "Сегодня", color: "var(--brand)" },
  { id: "tomorrow", title: "Завтра", color: "#6366F1" },
  { id: "week", title: "Неделя", color: "#8B5CF6" },
  { id: "month", title: "Месяц", color: "#F59E0B" },
  { id: "later", title: "Позже", color: "#14B8A6" },
  { id: "no_date", title: "Без даты", color: "#94A3B8" },
];

/** Классифицировать сделку по `nextStepAt` относительно `now` в один из {@link DATE_BUCKETS}.
 * Без даты → `no_date` (честный бакет, не «Позже»). Сутки считаются календарными (не 24ч-окном),
 * чтобы «Сегодня 23:59» и «Сегодня 00:01» попадали в одну колонку. */
export function dateBucketId(deal: Deal, now: number): DateBucketId {
  if (!deal.nextStepAt) return "no_date";
  const ts = Date.parse(deal.nextStepAt);
  if (Number.isNaN(ts)) return "no_date";

  const d0 = new Date(now);
  d0.setHours(0, 0, 0, 0);
  const startOfToday = d0.getTime();
  const DAY = 86_400_000;

  if (ts < startOfToday) return "overdue";
  if (ts < startOfToday + DAY) return "today";
  if (ts < startOfToday + 2 * DAY) return "tomorrow";
  if (ts < startOfToday + 7 * DAY) return "week";
  if (ts < startOfToday + 30 * DAY) return "month";
  return "later";
}

/** Сгруппировать сделки по бакетам дат действий (П4). Пустые бакеты возвращаются тоже
 * (title/color фиксированы) — вызывающий код сам решает, скрывать ли пустые колонки. */
export function groupByDateBucket(
  deals: Deal[],
  now: number,
): { id: DateBucketId; title: string; color: string; deals: Deal[] }[] {
  const byId = new Map<DateBucketId, Deal[]>(DATE_BUCKETS.map((b) => [b.id, []]));
  for (const d of deals) byId.get(dateBucketId(d, now))!.push(d);
  return DATE_BUCKETS.map((b) => ({ ...b, deals: byId.get(b.id)! }));
}

/** Строка «следующий шаг» карточки (слайс 4): todo (легаси-поле карточки лида) склеивается
 * с датой/временем действия через « · »; без todo — просто `nextStep`. Общая формула для
 * карточки канбана и композера назначения шага (NextStepComposer) — держать в одном месте. */
export function dealStepText(
  deal: Pick<Deal, "todo" | "nextStep" | "actionDate" | "actionTime">,
): string | undefined {
  return deal.todo
    ? [deal.todo, deal.actionDate, deal.actionTime].filter(Boolean).join(" · ")
    : deal.nextStep;
}

/** Слайс 4 (D, «след. шаг в 2 клика»): при смене стадии стоит авто-подставить дефолтный
 * пресет, когда целевая стадия открыта (не won/lost/cond_lost…) И у сделки ещё нет шага
 * (ни `todo`, ни `nextStep`) — сделку с уже назначенным шагом не перетираем. */
export function shouldAutoAssignNextStep(
  deal: Pick<Deal, "nextStep" | "todo">,
  targetStageId: string,
): boolean {
  return !isClosedStageId(targetStageId) && !deal.nextStep && !deal.todo;
}

/** Ранг срочности для сортировки колонки: просрочено → сегодня → завтра → остальные. */
const URGENCY_RANK: Partial<Record<DateBucketId, number>> = { overdue: 0, today: 1, tomorrow: 2 };

/** Порядок карточек в колонке (слайс 3): «деньги × срочность» — просроченные (по убыванию
 * взвешенной суммы) → сегодня → завтра → остальные по взвешенной DESC. Закрытые стадии
 * (won/lost/cond_lost) не сортируются — там важна хронология. До маунта (`now == null`)
 * порядок исходный (SSR и клиент совпадают — без прыжка гидрации). */
export function sortDealsForBoard(deals: Deal[], stageId: string, now: number | null): Deal[] {
  if (now == null || isClosedStageId(stageId)) return deals;
  return [...deals].sort((a, b) => {
    const ra = URGENCY_RANK[dateBucketId(a, now)] ?? 3;
    const rb = URGENCY_RANK[dateBucketId(b, now)] ?? 3;
    if (ra !== rb) return ra - rb;
    return weightedAmount(b, stageId) - weightedAmount(a, stageId);
  });
}
