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

/** Северность элемента очереди «Фокус дня» (слайс 5) — единственный источник цвета чипа
 *  на FocusPanel/карточке: 'crit' — горит прямо сейчас, 'warn' — сегодня/без шага,
 *  'info' — реанимация (условный отказ остывает, не горит так же сильно). */
export type FocusSeverity = "crit" | "warn" | "info";

/** Один элемент очереди «Фокус дня»: сделка + почему она требует внимания именно сейчас. */
export interface FocusQueueItem {
  deal: Deal;
  stageId: string;
  reason: string;
  severity: FocusSeverity;
}

/** Результат {@link focusQueue}: `items` — топ по приоритету длиной ≤ `cap`, `total` —
 *  полное число элементов ДО обрезки (для хвоста «+ещё N» на панели). */
export interface FocusQueueResult {
  items: FocusQueueItem[];
  total: number;
}

/**
 * Очередь «Фокус дня» (слайс 5): упорядоченный список «что делать сейчас» — вместо
 * сканирования колонок доски. Каждая сделка попадает НЕ БОЛЕЕ чем в одну категорию
 * (приоритет по порядку ниже); закрытые стадии (won/lost, {@link isClosedStageId})
 * исключены целиком. Приоритет:
 *  1. Просроченный шаг (`dateBucketId` → «overdue») — по weighted DESC.
 *  2. Шаг сегодня (bucket «today») — по weighted DESC.
 *  3. Реанимация: «Условный отказ» (id endsWith «cond_lost») старше {@link REVIVE_AFTER_DAYS}
 *     без касания ({@link reviveDays}) — по reviveDays DESC. Единственное правило, где
 *     участвует cond_lost — остальные его не видят (тот же гейт, что у {@link isStuck}).
 *  4. Открытые БЕЗ шага (ни `todo`, ни `nextStep`): сперва ПЕРВАЯ стадия переданного
 *     списка `stages` (стадия новой заявки — первое касание важнее прогрева уже идущей
 *     сделки) по daysInStage DESC, затем остальные открытые без шага — по weighted DESC.
 * `now == null` (SSR/до маунта) → пустой результат, без прыжка гидрации.
 */
export function focusQueue(
  stages: Pick<Stage, "id" | "deals">[],
  now: number | null,
  cap = 12,
): FocusQueueResult {
  if (now == null) return { items: [], total: 0 };

  type Ranked = FocusQueueItem & { sortKey: number };
  const overdue: Ranked[] = [];
  const dueToday: Ranked[] = [];
  const revive: Ranked[] = [];
  const noTouch: Ranked[] = [];
  const noStep: Ranked[] = [];

  stages.forEach((stage, idx) => {
    const revivable = stage.id.endsWith("cond_lost");
    if (isClosedStageId(stage.id) && !revivable) return; // won/lost — вне очереди целиком

    for (const deal of stage.deals) {
      if (revivable) {
        const days = reviveDays(deal, stage.id, now);
        if (days != null) {
          revive.push({
            deal,
            stageId: stage.id,
            reason: `реанимировать · ${days} дн`,
            severity: "info",
            sortKey: days,
          });
        }
        continue; // «условный отказ» участвует только в реанимации — не в overdue/без-шага
      }

      const bucket = dateBucketId(deal, now);
      if (bucket === "overdue") {
        const dueTs = Date.parse(deal.nextStepAt ?? deal.actionDate ?? "");
        // FIX-R1 (ревью 62c1a7d): overdue у dateBucketId — календарный (дедлайн вчера 20:00
        // уже overdue сегодня утром), а не 24-часовое окно от `now` — считаем от границы
        // календарных суток, иначе утром по вчерашней просрочке текст даёт «просрочен 0 дн».
        const startOfToday = new Date(now);
        startOfToday.setHours(0, 0, 0, 0);
        const days = Number.isNaN(dueTs)
          ? 1
          : Math.max(1, Math.ceil((startOfToday.getTime() - dueTs) / DAY_MS));
        overdue.push({
          deal,
          stageId: stage.id,
          reason: `просрочен ${days} дн`,
          severity: "crit",
          sortKey: weightedAmount(deal, stage.id),
        });
        continue;
      }
      if (bucket === "today") {
        dueToday.push({
          deal,
          stageId: stage.id,
          reason: "шаг сегодня",
          severity: "warn",
          sortKey: weightedAmount(deal, stage.id),
        });
        continue;
      }

      if (deal.nextStep || deal.todo) continue; // шаг назначен, но не горит — вне очереди

      const days = daysInStage(deal.stageChangedAt, now) ?? 0;
      if (idx === 0) {
        // Первая стадия переданного списка = стадия новой заявки (первое касание); для
        // секций «Все вместе» вызывающий код передаёт список стадий КОНКРЕТНОЙ секции —
        // первая стадия там её собственная (см. deals-workspace.tsx: combinedCardExtras).
        noTouch.push({
          deal,
          stageId: stage.id,
          reason: `без касания ${days} дн`,
          severity: days >= 1 ? "crit" : "warn",
          sortKey: days,
        });
      } else {
        noStep.push({
          deal,
          stageId: stage.id,
          reason: `без шага · в стадии ${days} дн`,
          severity: "warn",
          sortKey: weightedAmount(deal, stage.id),
        });
      }
    }
  });

  const byKeyDesc = (a: Ranked, b: Ranked) => b.sortKey - a.sortKey;
  [overdue, dueToday, revive, noTouch, noStep].forEach((bucket) => bucket.sort(byKeyDesc));

  const ordered = [...overdue, ...dueToday, ...revive, ...noTouch, ...noStep];
  const items: FocusQueueItem[] = ordered
    .slice(0, cap)
    .map(({ deal, stageId, reason, severity }) => ({ deal, stageId, reason, severity }));
  return { items, total: ordered.length };
}

// ──────────────────────── Цикл 8: единый чип внимания карточки ────────────────────────

/** Тон единого чипа внимания карточки ({@link cardAttention}) — определяет цвет:
 *  'crit' — сплошной красный (горит сильнее всего), 'warn' — красный мягкий,
 *  'revive' — оранжевый, 'soft' — янтарный, 'muted' — нейтральный. */
export type AttentionTone = "crit" | "warn" | "revive" | "soft" | "muted";

export interface CardAttention {
  label: string;
  tone: AttentionTone;
  title: string;
}

/**
 * Единый резолвер чипа внимания карточки (цикл 8): раньше в шапке карточки параллельно
 * рендерились actBucket/noTouchDays/noStep/reviveDays + отдельно days/stuck — конкурирующие
 * сигналы раздували шапку и путали взгляд. Возвращает ОДИН самый важный сигнал по приоритету
 * (сверху вниз, первое совпадение побеждает):
 *  1. Следующий шаг просрочен (`actBucket==="overdue"`).
 *  2. Новая заявка не тронута ≥1 дня (`noTouchDays>=1`) — первое касание важнее прогрева.
 *  3. Следующий шаг сегодня (`actBucket==="today"`).
 *  4. «Условный отказ» пора реанимировать (`reviveDays`).
 *  5. Следующий шаг завтра (`actBucket==="tomorrow"`).
 *  6. Висяк — долго без движения по стадии (`stuck` + `daysInStage`).
 *  7. Новая заявка без касания сегодня (`noTouchDays===0`) — ещё не горит, но заметно.
 *  8. Нет следующего шага вовсе (`noStep`).
 *  9. Иначе — нет сигнала (`null`), чип не рендерится.
 */
export function cardAttention(signals: {
  actBucket?: "overdue" | "today" | "tomorrow" | null;
  noTouchDays?: number | null;
  reviveDays?: number | null;
  stuck?: boolean;
  daysInStage?: number | null;
  noStep?: boolean;
}): CardAttention | null {
  const {
    actBucket = null,
    noTouchDays = null,
    reviveDays = null,
    stuck = false,
    daysInStage = null,
    noStep = false,
  } = signals;

  if (actBucket === "overdue") {
    return { label: "Просрочено", tone: "crit", title: "Следующий шаг просрочен" };
  }
  if (noTouchDays != null && noTouchDays >= 1) {
    return {
      label: `⏱ без касания ${noTouchDays} дн`,
      tone: "crit",
      title: "Новая заявка ещё не тронута — первое касание важнее прогрева",
    };
  }
  if (actBucket === "today") {
    return { label: "Сегодня", tone: "warn", title: "Следующий шаг сегодня" };
  }
  if (reviveDays != null) {
    return {
      label: `реанимировать · ${reviveDays} дн`,
      tone: "revive",
      title: "Условный отказ давно без касания — верни в работу",
    };
  }
  if (actBucket === "tomorrow") {
    return { label: "Завтра", tone: "soft", title: "Следующий шаг завтра" };
  }
  if (stuck && daysInStage != null) {
    return {
      label: `застрял ${daysInStage} дн`,
      tone: "soft",
      title: "Долго без движения по стадии",
    };
  }
  if (noTouchDays === 0) {
    return {
      label: "⏱ без касания",
      tone: "muted",
      title: "Новая заявка сегодня — сделай первое касание",
    };
  }
  if (noStep) {
    return {
      label: "нет шага",
      tone: "soft",
      title: "У сделки нет следующего шага — назначь действие",
    };
  }
  return null;
}

// ──────────────────────── Слайс 6: счёт в поток доски ────────────────────────

// «Оплачен» — ТОЛЬКО status="paid" (его ставит finance.payment.paid). posted означает
// «записан в 1С» и проставляется синхронно при выставлении счёта — деньги ещё НЕ дошли
// (ревью f4f825d: «✓ оплачен» для posted красил бы зелёным каждый свежий счёт).

/** Дней до даты по календарным суткам (не 24-часовое окно от `now`) — отрицательное,
 *  если дата уже прошла. Общий date-math для статуса счёта: бейдж карточки
 *  ({@link invoiceBadge}) и компактный блок «Документы» в drawer-preview форматируют
 *  СВОЙ текст поверх одного числа — не расходятся при правке. */
export function daysUntilDate(iso: string, now: number): number {
  const target = new Date(`${iso}T00:00:00`).getTime();
  const today = new Date(now);
  today.setHours(0, 0, 0, 0);
  return Math.round((target - today.getTime()) / DAY_MS);
}

export type InvoiceBadgeTone = "green" | "red" | "amber" | "neutral";

export interface InvoiceBadgeResult {
  label: string;
  tone: InvoiceBadgeTone;
}

/** Бейдж статуса счёта для карточки колонки «Счёт» (слайс 6, C) — «счёт выставлен 5 дней,
 *  не оплачен» не должен быть невидим на доске. «Оплачен» — только `paid`; для неоплаченного
 *  главное — срок резерва (`validUntil`: просрочен/истекает Kд), без срока `posted` даёт
 *  нейтральный «не оплачен». `null` — честный пропуск: ни оплаты, ни срока, ни записи в 1С. */
export function invoiceBadge(
  doc: { status: string; validUntil: string | null },
  now: number,
): InvoiceBadgeResult | null {
  if (doc.status === "paid") return { label: "✓ оплачен", tone: "green" };
  if (doc.validUntil) {
    const days = daysUntilDate(doc.validUntil, now);
    if (days < 0) return { label: "💳 просрочен", tone: "red" };
    return { label: `💳 истекает ${days}д`, tone: days <= 2 ? "amber" : "neutral" };
  }
  if (doc.status === "posted") return { label: "💳 не оплачен", tone: "neutral" };
  return null;
}

// ──────────────────────── Цикл 11: входящий сигнал (клиент ждёт ответа) ────────────────────────

/** Тон бейджа входящего сигнала карточки ({@link inboundSignal}): 'money' — непрочитанное
 *  сообщение (самый тёплый сигнал, это деньги), 'amber' — пропущенный звонок. */
export type InboundSignalTone = "money" | "amber";

export interface InboundSignalResult {
  label: string;
  title: string;
  tone: InboundSignalTone;
}

/**
 * Резолвер входящего сигнала карточки (цикл 11): тёплый клиент, приславший сообщение или
 * сделавший пропущенный звонок, был невидим на доске — продавец узнавал об этом, только
 * открыв сделку. Непрочитанный входящий — самый горячий сигнал (это деньги, которые нельзя
 * ронять) → приоритет 1; пропущенный звонок без непрочитанных сообщений — приоритет 2.
 * Ни того ни другого — сигнала нет (`null`), бейдж не рендерится.
 *
 * Не путать с {@link cardAttention}: та ось — тайминг МОЕГО следующего шага (я опаздываю),
 * эта — ждёт ли клиент МЕНЯ прямо сейчас (он горячий). Разные оси, оба чипа рендерятся рядом.
 */
export function inboundSignal(signals: { unread?: number; missed?: number }): InboundSignalResult | null {
  const { unread = 0, missed = 0 } = signals;
  if (unread > 0) {
    return {
      label: `💬 ${unread}`,
      tone: "money",
      title: `Клиент ждёт ответа — непрочитанных сообщений: ${unread}`,
    };
  }
  if (missed > 0) {
    return { label: "☎ пропущен", tone: "amber", title: "Пропущенный звонок от клиента без ответа" };
  }
  return null;
}

// ──────────────────────── Цикл 12: счета под риском (резерв уходит) ────────────────────────

/** Порог «скоро истекает» для очереди «Счета под риском» (в днях) — граница ВКЛЮЧЕНИЯ
 *  документа в очередь «дожать сейчас». Отдельный от {@link invoiceBadge} (там ≤2д — только
 *  порог цвета бейджа amber/neutral на карточке, не решение «показывать ли вообще»). */
const INVOICE_RISK_EXPIRING_DAYS = 3;

/** Северность элемента очереди «Счета под риском»: 'crit' — просрочен (деньги уже опаздывают),
 *  'warn' — истекает скоро ИЛИ резерв уже снят, а оплаты нет. */
export type InvoiceRiskSeverity = "crit" | "warn";

/** Один документ-счёт со сделкой — вход {@link invoicesAtRisk} (deals-workspace.tsx собирает
 *  батч-фетчем `fetchDocuments` по стадиям invoice/protected/contract). */
export interface InvoiceRiskEntry {
  deal: Deal;
  doc: {
    number: string;
    status: string;
    validUntil: string | null;
    reserveStatus: string;
    amount: number;
  };
}

/** Один элемент очереди «Счета под риском» — уже готов для отрисовки панелью. */
export interface InvoiceRiskItem {
  deal: Deal;
  docNumber: string;
  amount: number;
  reserveStatus: string;
  severity: InvoiceRiskSeverity;
  /** Подпись срочности: «просрочен N дн» / «истекает N дн[ · резерв уйдёт]» / «резерв снят…». */
  reason: string;
}

/** Результат {@link invoicesAtRisk}: `items` — топ по срочности длиной ≤ `cap`, `total` —
 *  полное число элементов ДО обрезки (для хвоста «+ещё N» на панели, как у {@link FocusQueueResult}). */
export interface InvoiceRiskResult {
  items: InvoiceRiskItem[];
  total: number;
}

/**
 * Очередь «Счета под риском» (цикл 12): счёт проведён (`posted` — записан в 1С), но НЕ
 * оплачен — почти закрытая выручка, которая утекает, а резерв товара под ней освобождается.
 * Без этой очереди продавец узнаёт о рисковом счёте, только листая колонки доски вручную.
 *
 * В очередь попадает `posted`-счёт (не `paid` — деньги уже дошли, не `draft`/иное — ещё не
 * выставлен всерьёз), если хотя бы одно верно:
 *  1. срок действия (`validUntil`) уже прошёл — просрочен (severity `crit`);
 *  2. срок истекает в пределах {@link INVOICE_RISK_EXPIRING_DAYS} дней (severity `warn`);
 *  3. резерв уже снят (`reserveStatus==="released"`), а счёт всё ещё не оплачен — товар
 *     свободен, но выручка так и не закрылась (severity `warn`, без даты — валидUntil
 *     может отсутствовать или быть в прошлом уже посчитан веткой 1/2 выше).
 *
 * Сортировка — «что дожимать первым»: просроченные впереди истекающих (внутри группы —
 * более срочные раньше: больше дней просрочки / меньше дней до истечения), при равной
 * срочности — крупнее сумма счёта раньше (деньги важнее). «Резерв снят» без активного
 * срока — последней группой (крупнее сумма раньше).
 */
export function invoicesAtRisk(
  entries: InvoiceRiskEntry[],
  now: number,
  cap = 20,
): InvoiceRiskResult {
  type Ranked = { item: InvoiceRiskItem; bucket: 0 | 1 | 2; sortDays: number };
  const ranked: Ranked[] = [];

  for (const { deal, doc } of entries) {
    if (doc.status !== "posted") continue; // paid — деньги дошли; draft — ещё не выставлен всерьёз

    if (doc.validUntil) {
      const days = daysUntilDate(doc.validUntil, now);
      if (days < 0) {
        ranked.push({
          item: {
            deal,
            docNumber: doc.number,
            amount: doc.amount,
            reserveStatus: doc.reserveStatus,
            severity: "crit",
            reason: `просрочен ${Math.abs(days)} дн`,
          },
          bucket: 0,
          sortDays: Math.abs(days),
        });
        continue;
      }
      if (days <= INVOICE_RISK_EXPIRING_DAYS) {
        const reserveNote = doc.reserveStatus === "reserved" ? " · резерв уйдёт" : "";
        ranked.push({
          item: {
            deal,
            docNumber: doc.number,
            amount: doc.amount,
            reserveStatus: doc.reserveStatus,
            severity: "warn",
            reason: `истекает ${days} дн${reserveNote}`,
          },
          bucket: 1,
          sortDays: days,
        });
        continue;
      }
    }
    if (doc.reserveStatus === "released") {
      ranked.push({
        item: {
          deal,
          docNumber: doc.number,
          amount: doc.amount,
          reserveStatus: doc.reserveStatus,
          severity: "warn",
          reason: "резерв снят, оплаты нет",
        },
        bucket: 2,
        sortDays: 0,
      });
    }
  }

  ranked.sort((a, b) => {
    if (a.bucket !== b.bucket) return a.bucket - b.bucket;
    if (a.sortDays !== b.sortDays) {
      // bucket 0 (просрочен): больше дней просрочки — раньше; bucket 1 (истекает): меньше
      // дней до истечения — раньше; bucket 2 не различается по sortDays (всегда 0).
      return a.bucket === 1 ? a.sortDays - b.sortDays : b.sortDays - a.sortDays;
    }
    return b.item.amount - a.item.amount;
  });

  return { items: ranked.slice(0, cap).map((r) => r.item), total: ranked.length };
}

// ──────────────────────── Слайс 9: мягкий скидочный гейт (защита прибыли) ────────────────────────

/** Результат {@link discountGate}: `minTotal` — минимально допустимая сумма по прайсу
 *  (Σ `min_price × qty` по позициям с известным `min_price`), `gap` — на сколько сделка ниже. */
export interface DiscountGateResult {
  minTotal: number;
  gap: number;
}

// ──────────────────────── Цикл 13: очередь «Дожать до плана» ────────────────────────

/** Порог затухания близости даты (в днях) — за {@link CLOSEABILITY_DECAY_DAYS} дней до
 *  ожидаемого закрытия близость уже вдвое ниже максимума (см. {@link closeProximity}). */
const CLOSEABILITY_DECAY_DAYS = 14;

/** Пол близости для далёкой даты — далёкий `expectedCloseDate` не обнуляет счёт совсем
 *  (сделка всё ещё открыта и в работе), просто перестаёт быть приоритетом «прямо сейчас». */
const CLOSEABILITY_FLOOR = 0.15;

/** Близость для сделки БЕЗ `expectedCloseDate` — среднее между «горит» и «далеко»: нет данных
 *  для суждения о сроке, но и открытая сделка без даты не должна тонуть в хвосте очереди
 *  только из-за пропуска поля (честная нейтральная оценка, не 0 и не максимум). */
const CLOSEABILITY_NO_DATE_PROXIMITY = 0.4;

/**
 * Близость ожидаемой даты закрытия сделки к «пора закрывать» (0..1) — множитель балла
 * {@link closeabilityQueue}. Дата уже прошла или сегодня → максимум (1): открытая сделка
 * с просроченным/сегодняшним ожиданием — дожимать СЕЙЧАС. Дата в будущем → плавное затухание
 * `{@link CLOSEABILITY_DECAY_DAYS} / (CLOSEABILITY_DECAY_DAYS + days)` (через 14 дней — 0.5,
 * через 42 — 0.25…), не ниже пола {@link CLOSEABILITY_FLOOR}. Нет даты или её не разобрать →
 * {@link CLOSEABILITY_NO_DATE_PROXIMITY} (честный нейтральный fallback, не крах на мусорной дате).
 */
export function closeProximity(expectedCloseDate: string | undefined, now: number): number {
  if (!expectedCloseDate) return CLOSEABILITY_NO_DATE_PROXIMITY;
  const days = daysUntilDate(expectedCloseDate, now);
  if (Number.isNaN(days)) return CLOSEABILITY_NO_DATE_PROXIMITY;
  if (days <= 0) return 1;
  return Math.max(CLOSEABILITY_FLOOR, CLOSEABILITY_DECAY_DAYS / (CLOSEABILITY_DECAY_DAYS + days));
}

/** Подпись срочности ожидаемой даты закрытия для карточки очереди {@link closeabilityQueue}. */
export function closeDateLabel(expectedCloseDate: string | undefined, now: number): string {
  if (!expectedCloseDate) return "дата не задана";
  const days = daysUntilDate(expectedCloseDate, now);
  if (Number.isNaN(days)) return "дата не задана";
  if (days === 0) return "ожид. сегодня";
  if (days < 0) return `просрочена на ${Math.abs(days)} дн`;
  return `ожид. через ${days} дн`;
}

/** Один элемент очереди «Дожать до плана» — сделка + разложенные множители балла (для
 *  отрисовки панелью: вероятность/взвешенная сумма/подпись даты, не только итоговый score). */
export interface CloseabilityItem {
  deal: Deal;
  stageId: string;
  score: number;
  probability: number;
  weighted: number;
  dateLabel: string;
}

/** Результат {@link closeabilityQueue}: `items` — топ по баллу длиной ≤ `cap`, `total` —
 *  полное число элементов ДО обрезки (тот же контракт, что {@link FocusQueueResult}). */
export interface CloseabilityResult {
  items: CloseabilityItem[];
  total: number;
}

/**
 * Очередь «Дожать до плана» (цикл 13): скорборд считает ЧИСЛО гэпа до плана продаж (см.
 * `planGap` в deals-workspace.tsx), но не говорит, какие ИМЕННО открытые сделки дожимать —
 * продавец сканирует колонки вручную. `closeabilityQueue` ранжирует открытые сделки
 * (терминальные и `cond_lost` — {@link isClosedStageId} — вне очереди целиком; для реанимации
 * cond_lost есть отдельная ветка {@link focusQueue}) по баллу «насколько реалистично закрыть
 * её СЕЙЧАС»:
 *
 * ```
 * score = probabilityFor(deal, stageId) × closeProximity(expectedCloseDate, now) × amount
 * ```
 *
 * — вероятность (явная или дефолт по стадии) и близость ожидаемой даты — множители 0..1
 * (см. {@link closeProximity}: просрочена/сегодня — максимум, далёкая/пустая — ниже, но не
 * ноль), сумма сделки — вес денег (крупная сделка с той же вероятностью важнее мелкой для
 * закрытия гэпа выручки). Сортировка — по score DESC; топ `cap` в `items`, `total` — полное
 * число ДО обрезки.
 */
export function closeabilityQueue(
  stages: Pick<Stage, "id" | "deals">[],
  now: number | null,
  cap = 12,
): CloseabilityResult {
  if (now == null) return { items: [], total: 0 };

  const ranked: CloseabilityItem[] = [];
  for (const stage of stages) {
    if (isClosedStageId(stage.id)) continue; // won/lost + cond_lost (endsWith "lost") — вне очереди
    for (const deal of stage.deals) {
      const probability = probabilityFor(deal, stage.id);
      const proximity = closeProximity(deal.expectedCloseDate, now);
      ranked.push({
        deal,
        stageId: stage.id,
        score: (probability / 100) * proximity * deal.amount,
        probability,
        weighted: weightedAmount(deal, stage.id),
        dateLabel: closeDateLabel(deal.expectedCloseDate, now),
      });
    }
  }
  ranked.sort((a, b) => b.score - a.score);
  return { items: ranked.slice(0, cap), total: ranked.length };
}

/**
 * Мягкий скидочный гейт (слайс 9) — прокси реальной маржи: методика ценообразования ещё не
 * готова (цены продавца на позиции нет), но у позиций есть справочный `min_price`. Если сумма
 * сделки ниже минимума по прайсу — повод предупредить (гейт НЕ блокирует действия, это дело
 * вызывающего UI — см. drawer). Позиции без `min_price` не участвуют в сумме (честный частичный
 * охват, не 0); если ни у одной позиции `min_price` не известен — гейта нет (`null`), как и
 * когда `amount` уже на уровне минимума или выше (граница — не нарушение).
 */
export function discountGate(
  items: { qty: number; min_price: number | null }[],
  amount: number,
): DiscountGateResult | null {
  let minTotal = 0;
  let hasKnown = false;
  for (const it of items) {
    if (it.min_price == null) continue;
    minTotal += it.min_price * it.qty;
    hasKnown = true;
  }
  if (!hasKnown || amount >= minTotal) return null;
  return { minTotal, gap: minTotal - amount };
}
