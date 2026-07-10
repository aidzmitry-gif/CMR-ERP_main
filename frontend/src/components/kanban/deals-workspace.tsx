"use client";

import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import clsx from "clsx";
import { Calendar, Clock, LayoutGrid, LayoutList, List, Plus, Search } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Children, useEffect, useId, useMemo, useRef, useState } from "react";
import { FunnelTotals } from "@/components/funnel-totals";
import { CreateDealModal } from "@/components/kanban/create-deal-modal";
import { DealCard, fetchManagersCached, type DealCardPatch } from "@/components/kanban/deal-card";
import { CallWindow } from "@/components/calls/call-window";
import { DealDrawerPreview } from "@/components/kanban/deal-drawer-preview";
import { FocusPanel } from "@/components/kanban/focus-panel";
import { LoseDealModal } from "@/components/kanban/lose-deal-modal";
import type { NextStepPatch } from "@/components/kanban/next-step-composer";
import {
  createDeal,
  createDealTask,
  fetchLossReasons,
  fetchPlans,
  getKpis,
  logActivity,
  loseDeal,
  updateDeal,
  updateDealStage,
  type DealInput,
} from "@/lib/api";
import {
  dateBucketId,
  daysInStage,
  focusQueue,
  groupByDateBucket,
  isClosedStageId,
  isOpenStage,
  isStuck,
  LOSS_REASONS,
  moveDealToStage,
  probabilityFor,
  recomputeStages,
  reviveDays,
  shouldAutoAssignNextStep,
  sortDealsForBoard,
  stageWeightedSum,
  weightedAmount,
} from "@/lib/board";
import { nextStepPreset, presetDateISO, STAGE_BY_ID } from "@/lib/sales-stages";
import { useCurrency } from "./currency-context";
import { computeFunnel } from "@/lib/funnel";
import type { Deal, Kpi, LossReason, Manager, Stage } from "@/lib/types";

/** Бейджи/плашки Сделки 2.0, вычисляемые для карточки из стадии и текущего времени. */
type CardExtras = {
  days: number | null;
  stuck: boolean;
  probability: number;
  weighted: number;
  lostReasonTitle?: string;
  wonResult: boolean;
  /** «Просрочено»/«Сегодня»/«Завтра» по next_step_at — чип срочности + цветная левая кромка. */
  actBucket: "overdue" | "today" | "tomorrow" | null;
  /** Открытая сделка без следующего шага — янтарный маркер «нет шага». */
  noStep: boolean;
  /** Слайс 5 (C): первая стадия списка (новая заявка) без шага — дни без первого касания;
   *  null — не первая стадия ИЛИ шаг уже есть (DealCard тогда решает через noStep как раньше). */
  noTouchDays: number | null;
  /** «Условный отказ» дольше порога без касания — чип «реанимировать · N дн» (слайс 3). */
  reviveDays: number | null;
  onLose?: () => void;
  /** Открыть окно звонка прямо с карточки канбана (тот же кокпит, что у drawer-preview). */
  onCall?: () => void;
  /** Меню карточки (⋯): ответственный/приоритет/избранное → оптимистичный патч + PATCH бэку. */
  onUpdate?: (fields: DealCardPatch) => void;
  /** Стадия сделки — композер «след. шаг» подбирает пресеты по ней (слайс 4). */
  stageId?: string;
  /** Слайс 4 («след. шаг в 2 клика»): назначить/очистить следующий шаг из композера
   *  карточки → оптимистичный патч + PATCH бэку (dealId уже закрыт в замыкании). */
  onNextStep?: (patch: NextStepPatch) => void;
};

/** Слайс 4 (D): дефолтный (первый) пресет стадии → патч для авто-назначения при
 *  смене стадии drag&drop (без ручного выбора в композере). Общая для основной доски
 *  и секций «Все вместе» — обе держат свой `setStages`, но пресет считается одинаково. */
function autoNextStepPatch(stageId: string): NextStepPatch {
  const preset = nextStepPreset(stageId);
  return { text: preset.label, atISO: presetDateISO(preset.offsetDays, Date.now()) };
}

/** Кап карточек в колонке (F): сотни сделок не душат доску DOM'ом; остальное — по кнопке. */
const CARD_CAP = 50;

/** Кнопка «Показать ещё N (из M)» под капом карточек колонки. */
function ShowMore({ total, limit, onMore }: { total: number; limit: number; onMore: () => void }) {
  if (total <= limit) return null;
  return (
    <button
      onClick={onMore}
      className="flex items-center justify-center rounded-xl border border-dashed border-line-strong py-2 text-xs font-medium text-muted hover:bg-sunken"
    >
      Показать ещё {Math.min(CARD_CAP, total - limit)} (из {total})
    </button>
  );
}

const PERIODS = [
  { key: "day", label: "День" },
  { key: "week", label: "Неделя" },
  { key: "month", label: "Месяц" },
  { key: "quarter", label: "Квартал" },
  { key: "year", label: "Год" },
];

/** П1 (решение оператора по сайту вариантов): первичный ряд скорборда — 8 метрик эталонного
 *  макета в его порядке, подписи макетные. Ключи без данных в бэке (расчётные: оплаты, валовая,
 *  новые сделки, конверсия, чек) — честный placeholder «нет данных», НЕ 0, до бэк-расчёта.
 *  Остальные KPI из /sales/kpis — вторым рядом под кнопкой-стрелкой «Ещё N показателей». */
const PRIMARY_CELLS: { key: string; label: string; headline?: boolean }[] = [
  { key: "ship_plan", label: "Выручка (отгрузки)", headline: true },
  { key: "payments_vat", label: "Оплаты с НДС" },
  { key: "gross_profit", label: "Прибыль валовая" },
  { key: "new_deals_count", label: "Новые сделки" },
  { key: "won_count", label: "Успешные" },
  { key: "invoice_payment_conv", label: "Конв. счёт→оплата" },
  { key: "calls_all", label: "Звонки (хол.)" },
  { key: "avg_deal", label: "Средний чек" },
];

/** Период в винительном падеже для chip-прогноза («Закроем месяц на ~X% плана»). */
const PERIOD_ACC: Record<string, string> = {
  day: "день", week: "неделю", month: "месяц", quarter: "квартал", year: "год",
};

/** period=«YYYY-MM» — произвольный месяц (input type=month), не relative-ключ. */
const MONTH_PERIOD_RE = /^(\d{4})-(\d{2})$/;

/** Подзаголовок шапки скорборда: контекст периода (как sb-sub макета). */
function periodSubLabel(period: string, now: number | null): string {
  if (now == null) return "";
  const d = new Date(now);
  const y = d.getFullYear();
  const monthMatch = MONTH_PERIOD_RE.exec(period);
  if (monthMatch) {
    const mi = Number(monthMatch[2]) - 1;
    const m = MONTH_NOM[mi] ?? "";
    return `${m[0]?.toUpperCase() ?? ""}${m.slice(1)} ${monthMatch[1]} · выбранный месяц`;
  }
  if (period === "day") return `${d.getDate()} ${MONTH_GEN[d.getMonth()]} ${y} · сегодня`;
  if (period === "week") return "текущая неделя";
  if (period === "month") {
    const m = MONTH_NOM[d.getMonth()];
    return `${m[0].toUpperCase()}${m.slice(1)} ${y}`;
  }
  if (period === "quarter") return `${Math.floor(d.getMonth() / 3) + 1} квартал ${y}`;
  return `${y} год`;
}

function pluralDeals(n: number): string {
  const d10 = n % 10;
  const d100 = n % 100;
  if (d10 === 1 && d100 !== 11) return "сделка";
  if (d10 >= 2 && d10 <= 4 && (d100 < 12 || d100 > 14)) return "сделки";
  return "сделок";
}

function pluralWorkdays(n: number): string {
  const d10 = n % 10;
  const d100 = n % 100;
  if (d10 === 1 && d100 !== 11) return "рабочий день";
  if (d10 >= 2 && d10 <= 4 && (d100 < 12 || d100 > 14)) return "рабочих дня";
  return "рабочих дней";
}

const MONTH_GEN = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];
const MONTH_NOM = [
  "январь", "февраль", "март", "апрель", "май", "июнь",
  "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
];

/** Рабочих дней (пн–пт) с текущей даты до конца месяца включительно. */
function workingDaysLeft(now: number): number {
  const d = new Date(now);
  const year = d.getFullYear();
  const month = d.getMonth();
  const lastDay = new Date(year, month + 1, 0).getDate();
  let count = 0;
  for (let day = d.getDate(); day <= lastDay; day++) {
    const wd = new Date(year, month, day).getDay();
    if (wd !== 0 && wd !== 6) count++;
  }
  return count;
}

// ponytail: demo-ставка валовой маржи для прогноза. Реальная — из landed cost
// (закупки); методика цены ещё разрабатывается ([[pricing-calculation-todo]]).
const DEMO_MARGIN_RATE = 0.22;

/** Баннер планирования: под конец месяца напоминает составить план на следующий и
 *  согласовать с РОПом (порт sales-board-mockup.html). Считается от текущей даты;
 *  `now` приходит после маунта (см. DealsWorkspace) — до него баннера нет. */
function PlanBanner({ now }: { now: number | null }) {
  if (now == null) return null;
  const left = workingDaysLeft(now);
  if (left > 7) return null; // нудж только в последнюю рабочую неделю месяца
  const d = new Date(now);
  const cur = MONTH_GEN[d.getMonth()];
  const next = MONTH_NOM[(d.getMonth() + 1) % 12];
  return (
    <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-amber-300/60 bg-amber-50 px-4 py-3 text-[13px] text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">
      <span aria-hidden>📋</span>
      <span>
        До конца {cur} — <b>{left} {pluralWorkdays(left)}</b>. Пора составить личный план на{" "}
        <b>{next}</b> и согласовать с РОПом.
      </span>
      <Link
        href="/crm/rop/planning"
        className="ml-auto rounded-lg bg-accent px-3.5 py-1.5 text-[12.5px] font-semibold text-white hover:bg-accent-ink"
      >
        Составить план на {next}
      </Link>
    </div>
  );
}

/** Вертикальный разделитель pipeline-строки — модульный: React-компилятор запрещает
 *  создавать компоненты во время рендера. */
const Sep = () => <span className="hidden h-4 w-px bg-line sm:block" aria-hidden />;

/** Pipeline-строка под скорбордом (порт макета): живые срезы открытого pipeline —
 *  кол-во/сумма/взвешенный прогноз (SALES-44)/висяки (SALES-43). Маржа — DEMO-ставка
 *  22% (реальная — из landed cost закупок; методика цены ещё разрабатывается). */
function PipelineRow({
  stages,
  now,
  fmt,
  chip,
  planGap,
}: {
  stages: Stage[];
  now: number | null;
  fmt: (value: number) => string;
  /** П3 (макет): chip-прогноз закрытия периода («Закроем месяц на ~X% плана»). */
  chip?: string | null;
  /** Гэп до плана периода (слайс 3): сколько выручки не хватает и ≈сколько это сделок
   * со средним чеком. null — плана/чека в данных нет (honest-empty, строка не рисуется). */
  planGap?: { gap: number; deals: number; avg: number } | null;
}) {
  const open = stages.filter(isOpenStage);
  const count = open.reduce((n, s) => n + s.deals.length, 0);
  const sum = open.reduce((n, s) => n + s.deals.reduce((a, d) => a + d.amount, 0), 0);
  const weighted = open.reduce((n, s) => n + stageWeightedSum(s), 0);
  const margin = Math.round(weighted * DEMO_MARGIN_RATE);
  const stuck =
    now == null
      ? null
      : stages.reduce((n, s) => n + s.deals.filter((d) => isStuck(d, s.id, now)).length, 0);
  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl bg-surface px-4 py-3 text-[13px] shadow-card">
      <span className="text-muted">
        В работе: <b className="text-ink">{count}</b> {pluralDeals(count)}
      </span>
      <Sep />
      <span className="text-muted">
        Сумма pipeline: <b className="text-ink">{fmt(sum)}</b>
      </span>
      <Sep />
      <span className="text-muted">
        Взвешенный прогноз <span className="text-faint">(выручка)</span>:{" "}
        <b className="text-accent-ink">≈ {fmt(weighted)}</b>
      </span>
      <Sep />
      <span className="text-muted">
        Прогноз маржи{" "}
        <span
          className="text-faint"
          title="Демо-ставка маржи 22%. Реальная маржа — из landed cost (закупки); методика цены ещё разрабатывается."
        >
          (вал. прибыль · демо 22%)
        </span>
        : <b className="text-money">≈ {fmt(margin)}</b>
      </span>
      <Sep />
      <span className="text-muted">
        Висяки: <b className="text-amber-600">{stuck ?? "—"}</b>
      </span>
      {planGap && (
        <>
          <Sep />
          <span
            className="text-muted"
            title="План выручки периода минус факт; сделки — по среднему чеку (факт won или плановый)."
          >
            До плана: <b className="text-ink">{fmt(planGap.gap)}</b> · ≈{planGap.deals}{" "}
            {pluralDeals(planGap.deals)} со ср. чеком {fmt(planGap.avg)}
          </span>
        </>
      )}
      {chip && (
        <span className="ml-auto rounded-lg bg-accent-soft px-2.5 py-1 text-[12.5px] font-semibold text-accent-ink">
          {chip}
        </span>
      )}
    </div>
  );
}

function DraggableDeal({
  deal,
  extras,
  fmt,
  onPreview,
  onOpen,
}: {
  deal: Deal;
  extras: CardExtras;
  fmt: (value: number) => string;
  onPreview: (d: Deal) => void;
  onOpen: (d: Deal) => void;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: deal.id });
  // Click vs double-click: первый клик → setTimeout(230ms) → onPreview;
  // второй клик в окне таймера → clear + onOpen. Глушим встроенный <Link>
  // у DealCard через preventDefault — навигация идёт через router.push в onOpen.
  // Не мешаем клику по интерактивным дочерним (кнопка «Отказ», меню карточки ⋯).
  const clickTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (clickTimer.current) clearTimeout(clickTimer.current);
  }, []);

  function handleClickCapture(e: React.MouseEvent) {
    const target = e.target as HTMLElement;
    // Кнопки (отказ/звонок) и попап меню ⋯ (data-card-menu) — не глушим их клики.
    if (target.closest("button") || target.closest("[data-card-menu]")) return;
    e.preventDefault();
    e.stopPropagation();
    if (clickTimer.current) {
      clearTimeout(clickTimer.current);
      clickTimer.current = null;
      onOpen(deal);
      return;
    }
    clickTimer.current = setTimeout(() => {
      clickTimer.current = null;
      onPreview(deal);
    }, 230);
  }

  return (
    <div
      ref={setNodeRef}
      data-testid={`deal-card-${deal.id}`}
      {...attributes}
      {...listeners}
      onClickCapture={handleClickCapture}
      className={isDragging ? "opacity-40" : ""}
    >
      <DealCard deal={deal} fmt={fmt} {...extras} />
    </div>
  );
}

function Column({
  stage,
  onAdd,
  fmt,
  stuckCount = 0,
  children,
}: {
  stage: Stage;
  onAdd: () => void;
  fmt: (value: number) => string;
  /** Застрявших сделок в колонке (isStuck) — янтарный счётчик в шапке при N>0. */
  stuckCount?: number;
  children: React.ReactNode;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: stage.id });
  // Взвешенная сумма по колонке (SALES-44) — только для открытого pipeline с карточками.
  // Охват — тот же isOpenStage, что и в итоге PipelineRow: иначе cond_lost (5%) показал бы
  // «взвешенно» в колонке, не входя в общий прогноз → Σ колонок ≠ итогу строки.
  const showWeighted = isOpenStage(stage) && stage.deals.length > 0;
  const weighted = stageWeightedSum(stage);
  // F: кап рендера карточек — длинные колонки не рисуют сотни DOM-узлов разом.
  const [limit, setLimit] = useState(CARD_CAP);
  const items = Children.toArray(children);
  return (
    <div className="flex w-[300px] shrink-0 flex-col gap-3">
      <div className="overflow-hidden rounded-xl bg-surface shadow-card">
        <div className="h-1" style={{ backgroundColor: stage.color }} />
        <div className="px-4 py-3">
          <div className="flex items-center justify-between gap-2 font-semibold text-ink">
            <span className="truncate">{stage.title}</span>
            <span className="shrink-0 rounded-md bg-sunken px-2 text-xs font-semibold leading-5 text-faint">
              {stage.count}
            </span>
          </div>
          <div className="mt-0.5 text-xs text-muted">
            {stage.count} {pluralDeals(stage.count)} · {fmt(stage.sum)}
          </div>
          {showWeighted && (
            <>
              <div className="mt-0.5 text-[11px] font-semibold text-accent-ink">
                взвешенно: {fmt(weighted)}
              </div>
              <div
                className="text-[11px] font-semibold text-money"
                title="Демо-ставка маржи 22%. Реальная — из landed cost (закупки); методика цены ещё разрабатывается."
              >
                прогноз маржи: ~{fmt(Math.round(weighted * DEMO_MARGIN_RATE))}
              </div>
            </>
          )}
          {stuckCount > 0 && (
            <div className="mt-0.5 text-[11px] font-semibold text-amber-600 dark:text-amber-400">
              🕒 застряло: {stuckCount}
            </div>
          )}
        </div>
      </div>
      <div
        ref={setNodeRef}
        data-testid={`stage-column-${stage.id}`}
        className={clsx(
          "flex min-h-20 flex-col gap-3 rounded-xl p-1 transition-colors",
          isOver && "bg-accent-soft ring-2 ring-accent",
        )}
      >
        {items.slice(0, limit)}
        <ShowMore total={items.length} limit={limit} onMore={() => setLimit((l) => l + CARD_CAP)} />
        <button
          onClick={onAdd}
          className="flex items-center justify-center gap-1.5 rounded-xl border border-dashed border-line-strong py-2.5 text-xs font-medium text-muted hover:bg-sunken"
        >
          <Plus size={14} /> Добавить сделку
        </button>
      </div>
    </div>
  );
}

/** «Все вместе» (мокап sales-board-mockup.html, COMBINED, ~1912-1915): доска одной
 *  воронки — заголовок секции + канбан с горизонтальным скроллом колонок. Своя
 *  DndContext на секцию (перенос сделки внутри своей же воронки), reuse Column/DraggableDeal —
 *  логика канбана не дублируется. */
function FunnelSection({
  title,
  color,
  initialStages,
  fmt,
  now,
  cardExtras,
  onPreview,
  onOpen,
  onAddDeal,
}: {
  title: string;
  color: string;
  initialStages: Stage[];
  fmt: (value: number) => string;
  /** Время маунта родителя — для сортировки «деньги × срочность» (sortDealsForBoard). */
  now: number | null;
  cardExtras: (deal: Deal, stageId: string, stages: Stage[]) => CardExtras;
  onPreview: (d: Deal) => void;
  onOpen: (d: Deal) => void;
  onAddDeal: (stageId: string, sectionStages: Stage[]) => void;
}) {
  const [stages, setStages] = useState<Stage[]>(initialStages);
  const [active, setActive] = useState<Deal | null>(null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));
  const dndId = useId();

  // Родитель SSR-рефрешит (router.refresh()) после создания сделки в секции — синхронизируем
  // локальный стейт с новым `initialStages`, иначе секция не увидит новую карточку.
  useEffect(() => {
    setStages(initialStages);
  }, [initialStages]);

  function handleDragStart(e: DragStartEvent) {
    const id = String(e.active.id);
    setActive(stages.flatMap((s) => s.deals).find((d) => d.id === id) ?? null);
  }

  function handleDragEnd(e: DragEndEvent) {
    setActive(null);
    const dealId = String(e.active.id);
    const targetStage = e.over ? String(e.over.id) : null;
    if (!targetStage) return;
    const found = stages.flatMap((s) => s.deals).find((d) => d.id === dealId) ?? null;
    setStages((prev) => moveDealToStage(prev, dealId, targetStage));
    void updateDealStage(dealId, targetStage);
    // D (слайс 4): целевая стадия открыта и у сделки ещё нет шага — подставляем дефолтный
    // пресет стадии (не перетираем сделку с уже назначенным шагом).
    if (found && shouldAutoAssignNextStep(found, targetStage)) {
      patchSectionNextStep(dealId, autoNextStepPatch(targetStage));
    }
  }

  /** Патч полей из меню карточки (⋯): доска секции живёт в локальном стейте —
   *  оптимистично правим здесь + fire-and-forget PATCH бэку. */
  function patchSectionDeal(dealId: string, fields: DealCardPatch) {
    setStages((prev) =>
      prev.map((s) => ({
        ...s,
        deals: s.deals.map((d) => (d.id === dealId ? { ...d, ...fields } : d)),
      })),
    );
    void updateDeal(dealId, fields);
  }

  /** Слайс 4: назначить/очистить следующий шаг из композера карточки секции «Все вместе» —
   *  тот же оптимистичный патч + PATCH бэку, что и на основной доске (handleNextStep),
   *  но пишет в локальный стейт секции. Гасим legacy todo/actionDate/actionTime — иначе
   *  dealStepText (board.ts) отдал бы приоритет старому todo поверх нового next_step. */
  function patchSectionNextStep(dealId: string, patch: NextStepPatch) {
    setStages((prev) =>
      prev.map((s) => ({
        ...s,
        deals: s.deals.map((d) =>
          d.id === dealId
            ? {
                ...d,
                nextStep: patch.text ?? undefined,
                nextStepAt: patch.atISO ?? undefined,
                todo: undefined,
                actionDate: undefined,
                actionTime: undefined,
              }
            : d,
        ),
      })),
    );
    void updateDeal(dealId, { next_step: patch.text, next_step_at: patch.atISO });
  }

  const total = stages.reduce((n, s) => n + s.count, 0);

  return (
    <div className="mt-5">
      <div
        className="mb-2.5 flex items-center gap-2 border-l-[3px] pl-2.5 text-sm font-bold text-ink"
        style={{ borderColor: color }}
      >
        <span aria-hidden>▦</span>
        {title}
        <span className="text-xs font-normal text-faint">
          · {total} {pluralDeals(total)}
        </span>
      </div>
      <DndContext id={dndId} sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
        <div className="flex gap-4 overflow-x-auto pb-2 thin-scroll">
          {stages.map((stage) => {
            const extrasByDeal = sortDealsForBoard(stage.deals, stage.id, now).map(
              (deal) => [deal, cardExtras(deal, stage.id, stages)] as const,
            );
            return (
              <Column
                key={stage.id}
                stage={stage}
                fmt={fmt}
                stuckCount={extrasByDeal.filter(([, x]) => x.stuck).length}
                onAdd={() => onAddDeal(stage.id, stages)}
              >
                {extrasByDeal.map(([deal, extras]) => (
                  <DraggableDeal
                    key={deal.id}
                    deal={deal}
                    extras={{
                      ...extras,
                      onUpdate: (f) => patchSectionDeal(deal.id, f),
                      onNextStep: (patch) => patchSectionNextStep(deal.id, patch),
                    }}
                    fmt={fmt}
                    onPreview={onPreview}
                    onOpen={onOpen}
                  />
                ))}
              </Column>
            );
          })}
        </div>
        <DragOverlay>
          {active ? (
            <div className="w-[280px] rotate-2">
              <DealCard deal={active} fmt={fmt} />
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>
    </div>
  );
}

/** Колонка группировки «По датам действий» (П4) — как {@link Column}, но без drag&drop
 * (перенос карточки сюда не меняет её дату шага) и с фикс. цветом бакета вместо стадии. */
function DateColumn({
  bucket,
  fmt,
  children,
}: {
  bucket: { id: string; title: string; color: string; deals: Deal[] };
  fmt: (value: number) => string;
  children: React.ReactNode;
}) {
  const sum = bucket.deals.reduce((a, d) => a + d.amount, 0);
  // F: тот же кап карточек, что и в стадийной колонке (бакет «Без даты» собирает сотни сделок).
  const [limit, setLimit] = useState(CARD_CAP);
  const items = Children.toArray(children);
  return (
    <div className="flex w-[300px] shrink-0 flex-col gap-3">
      <div className="overflow-hidden rounded-xl bg-surface shadow-card">
        <div className="h-1" style={{ backgroundColor: bucket.color }} />
        <div className="px-4 py-3">
          <div className="flex items-center justify-between gap-2 font-semibold text-ink">
            <span className="truncate">{bucket.title}</span>
            <span className="shrink-0 rounded-md bg-sunken px-2 text-xs font-semibold leading-5 text-faint">
              {bucket.deals.length}
            </span>
          </div>
          <div className="mt-0.5 text-xs text-muted">
            {bucket.deals.length} {pluralDeals(bucket.deals.length)} · {fmt(sum)}
          </div>
        </div>
      </div>
      <div className="flex min-h-20 flex-col gap-3 rounded-xl p-1">
        {bucket.deals.length > 0 ? (
          <>
            {items.slice(0, limit)}
            <ShowMore
              total={items.length}
              limit={limit}
              onMore={() => setLimit((l) => l + CARD_CAP)}
            />
          </>
        ) : (
          <div className="rounded-xl border border-dashed border-line-strong py-4 text-center text-xs text-faint">
            Пусто
          </div>
        )}
      </div>
    </div>
  );
}

/** Карточка сделки для группировки «По датам действий» — тот же клик-превью/двойной клик
 * что и {@link DraggableDeal}, но без dnd-kit хуков (тащить между датами тут нельзя). */
function StaticDealCard({
  deal,
  extras,
  fmt,
  onPreview,
  onOpen,
}: {
  deal: Deal;
  extras: CardExtras;
  fmt: (value: number) => string;
  onPreview: (d: Deal) => void;
  onOpen: (d: Deal) => void;
}) {
  const clickTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (clickTimer.current) clearTimeout(clickTimer.current);
  }, []);

  function handleClickCapture(e: React.MouseEvent) {
    const target = e.target as HTMLElement;
    if (target.closest("button") || target.closest("[data-card-menu]")) return;
    e.preventDefault();
    e.stopPropagation();
    if (clickTimer.current) {
      clearTimeout(clickTimer.current);
      clickTimer.current = null;
      onOpen(deal);
      return;
    }
    clickTimer.current = setTimeout(() => {
      clickTimer.current = null;
      onPreview(deal);
    }, 230);
  }

  return (
    <div data-testid={`deal-card-${deal.id}`} onClickCapture={handleClickCapture}>
      <DealCard deal={deal} fmt={fmt} {...extras} />
    </div>
  );
}

// ── План/Факт: компактный скорборд (перенос блока с sales-board-mockup.html) ────
// Доля прошедшего времени периода (0..1) из реального `now` — база метки темпа и прогноза run-rate.
function periodElapsed(now: number, period: string): number {
  const d = new Date(now);
  const clamp = (x: number) => Math.max(0.02, Math.min(1, x));
  const dayFrac = (d.getHours() * 60 + d.getMinutes()) / (24 * 60);
  if (period === "day") {
    const cur = d.getHours() * 60 + d.getMinutes();
    return clamp((cur - 9 * 60) / (18 * 60 - 9 * 60)); // рабочий день 9:00–18:00
  }
  if (period === "week") {
    const dow = (d.getDay() + 6) % 7; // 0=Пн … 6=Вс
    return clamp((Math.min(dow, 5) + (dow < 5 ? dayFrac : 0)) / 5); // Пн–Пт
  }
  if (period === "month") {
    const dim = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
    return clamp((d.getDate() - 1 + dayFrac) / dim);
  }
  if (period === "quarter") {
    const qs = new Date(d.getFullYear(), Math.floor(d.getMonth() / 3) * 3, 1).getTime();
    const qe = new Date(d.getFullYear(), Math.floor(d.getMonth() / 3) * 3 + 3, 1).getTime();
    return clamp((now - qs) / (qe - qs));
  }
  const ys = new Date(d.getFullYear(), 0, 1).getTime();
  const ye = new Date(d.getFullYear() + 1, 0, 1).getTime();
  return clamp((now - ys) / (ye - ys));
}

/** Светофор выполнения (Сделки 2.0): ≥100 зелёный · ≥70 янтарь · иначе красный. */
function kpiTone(pct: number): { bar: string; text: string; dot: string } {
  if (pct >= 100) return { bar: "bg-emerald-500", text: "text-emerald-600 dark:text-emerald-400", dot: "bg-emerald-500" };
  if (pct >= 70) return { bar: "bg-amber-500", text: "text-amber-600 dark:text-amber-400", dot: "bg-amber-500" };
  return { bar: "bg-red-500", text: "text-red-600 dark:text-red-400", dot: "bg-red-500" };
}

/** Цвет прогноза (продажи: больше — лучше). */
function projClass(pct: number): string {
  if (pct >= 100) return "text-emerald-600 dark:text-emerald-400";
  if (pct >= 85) return "text-amber-600 dark:text-amber-400";
  return "text-red-600 dark:text-red-400";
}

/** Ячейка-заглушка для метрик макета без данных в бэке: честное «нет данных», НЕ 0. */
function PlanFactPlaceholder({ label }: { label: string }) {
  return (
    <div className="min-w-0 bg-surface px-4 py-3">
      <div className="text-[11.5px] leading-tight text-muted">{label}</div>
      <div className="mt-1.5 text-[22px] font-bold leading-none tracking-tight text-faint">—</div>
      <div className="relative mt-2 h-1.5 overflow-hidden rounded-full bg-sunken" />
      <div className="mt-1.5 text-[11px] text-faint">нет данных · появится с бэк-расчётом</div>
    </div>
  );
}

/** Ячейка План/Факт: разметка как в скорборде мокапа (плоская, без карточки-бокса). */
function PlanFactCell({
  kpi,
  fmt,
  elapsed,
  onLog,
  label,
  headline = false,
  subnote,
}: {
  kpi: Kpi;
  fmt: (v: number) => string;
  elapsed: number | null;
  onLog?: () => void;
  /** Переопределение подписи (первичный ряд использует подписи макета). */
  label?: string;
  /** Первая метрика макета — крупнее (cell.headline). */
  headline?: boolean;
  /** Доп. строка под значением (напр. «из них N хол.»). */
  subnote?: string;
}) {
  const t = kpiTone(kpi.percent);
  const value = kpi.money ? fmt(kpi.value) : kpi.value;
  const target = kpi.money ? fmt(kpi.target) : kpi.target;
  // прогноз run-rate — только когда прошло ≥10% периода (иначе оценка неустойчива).
  const showProj = elapsed != null && elapsed >= 0.1 && kpi.target > 0;
  const projVal = showProj ? Math.round(kpi.value / elapsed) : 0;
  const projPct = showProj ? Math.round((projVal / kpi.target) * 100) : 0;
  return (
    <div className="min-w-0 bg-surface px-4 py-3">
      <div className="flex items-start justify-between gap-2">
        <div className="truncate text-[11.5px] leading-tight text-muted">{label ?? kpi.label}</div>
        {onLog && !kpi.money && (
          <button
            onClick={onLog}
            title="Отметить (+1)"
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-faint hover:bg-sunken hover:text-accent-ink"
          >
            <Plus size={14} />
          </button>
        )}
      </div>
      <div
        className={clsx(
          "mt-1.5 truncate font-bold leading-none tracking-tight text-ink",
          headline ? "text-[26px]" : "text-[22px]",
        )}
      >
        {value}
        <span className="whitespace-nowrap text-[13px] font-normal text-faint"> / {target}</span>
      </div>
      {subnote && <div className="mt-0.5 text-[11px] text-faint">{subnote}</div>}
      <div className="relative mt-2 h-1.5 overflow-hidden rounded-full bg-sunken">
        <div className={`h-full rounded-full ${t.bar}`} style={{ width: `${Math.min(kpi.percent, 100)}%` }} />
        {elapsed != null && (
          <span
            className="absolute -top-px -bottom-px w-0.5 bg-ink/40"
            style={{ left: `${Math.min(elapsed * 100, 100)}%` }}
            title={`нужно к этому моменту: ${Math.round(elapsed * 100)}%`}
          />
        )}
      </div>
      <div className={`mt-1.5 flex items-center gap-1.5 text-[11px] font-semibold ${t.text}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${t.dot}`} />
        {kpi.percent}% выполнено
      </div>
      {showProj && (
        <div className="mt-1 truncate text-[10.5px] text-muted">
          → идём на <span className="font-bold text-ink">{kpi.money ? fmt(projVal) : projVal}</span>{" "}
          <span className={`font-bold ${projClass(projPct)}`}>({projPct}%)</span>
        </div>
      )}
    </div>
  );
}

/** Цвет заголовка секции в «Все вместе» (мокап sales-board-mockup.html, COMBINED) по
 *  коду воронки; неизвестный код (созданный через редактор стадий) — акцентный дефолт. */
const FUNNEL_SECTION_COLOR: Record<string, string> = {
  new_clients: "#2563EB",
  repeat_clients: "#FB923C",
  tenders: "#14B8A6",
};

export function DealsWorkspace({
  initialStages,
  initialKpis,
  funnelTabs,
  combinedStages,
  demoData = false,
}: {
  initialStages: Stage[];
  initialKpis: Kpi[];
  funnelTabs?: React.ReactNode;
  /** «Все вместе» (funnel=all): доска каждой воронки своей секцией, одна под другой. */
  combinedStages?: { code: string; title: string; stages: Stage[] }[];
  /** SSR-фетч доски упал в mock-fallback (backend недоступен) — показать плашку «демо». */
  demoData?: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const { fmt } = useCurrency();
  const [stages, setStages] = useState<Stage[]>(initialStages);
  // A (слайс 3): менеджеры для переключателя «Чья доска» — общий кэш с меню карточки (⋯).
  const [managers, setManagers] = useState<Manager[]>([]);
  const [kpis, setKpis] = useState<Kpi[]>(initialKpis);
  const [period, setPeriod] = useState("day");
  const [activeDeal, setActiveDeal] = useState<Deal | null>(null);
  // single-click по сделке открывает drawer-preview (sales-card-expanded.html);
  // double-click уходит на /crm/deals/[id] (полная страница, sales-card-full.html).
  const [previewDeal, setPreviewDeal] = useState<Deal | null>(null);
  // Слайс 5: панель «Фокус дня» — упорядоченная очередь «что делать сейчас» (focusQueue).
  const [focusOpen, setFocusOpen] = useState(false);
  // callDeal = открыто окно звонка по этой сделке (тот же кокпит, что и у лида).
  const [callDeal, setCallDeal] = useState<Deal | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalStage, setModalStage] = useState<string>(initialStages[0]?.id ?? "new");
  // «Все вместе»: клик «Добавить сделку» в секции воронки должен предложить стадии ЭТОЙ
  // воронки в модалке, а не дефолтные new_clients (`stages`) — храним стадии секции-источника.
  const [modalStages, setModalStages] = useState<Stage[] | null>(null);
  const [query, setQuery] = useState("");
  // Фильтры шапки — не локальный state: кнопка «Фильтры» живёт в шапке страницы (FiltersMenu,
  // решение оператора), отдельное поддерево React от доски. Тот же URL-паттерн, что у `funnel`:
  // ?priority= (приоритет), ?owner= (ответственный), ?attn= (внимание: overdue | no_step).
  const searchParams = useSearchParams();
  const priority = searchParams.get("priority");
  const ownerFilter = searchParams.get("owner");
  const attn = searchParams.get("attn");
  const [view, setView] = useState<"board" | "list">("board");
  // П4 (слайс 4): переключатель группировки канбана — по стадиям (умолчание) / по датам
  // следующего действия (next_step_at). Действует только для view="board".
  const [groupBy, setGroupBy] = useState<"stage" | "dates">("stage");
  const [stuckOnly, setStuckOnly] = useState(false);
  // Быстрый фильтр «действие сегодня/завтра» (мокап: actSeg «🔴 На сегодня / 🟠 На завтра»,
  // повторный клик снимает). Дата — next_step_at через канон dateBucketId (board.ts).
  const [actFilter, setActFilter] = useState<"today" | "tomorrow" | null>(null);
  const [now, setNow] = useState<number | null>(null);
  const [lossReasons, setLossReasons] = useState<LossReason[]>(LOSS_REASONS);
  const [losing, setLosing] = useState<{ dealId: string; label: string } | null>(null);
  // П1: второй ряд метрик под стрелкой «Ещё N показателей» (состояние переживает перезагрузку).
  const [moreKpis, setMoreKpis] = useState(false);
  // П2: «план продаж согласован РОПом» в подзаголовке — если на текущий месяц есть approved-план.
  const [planApproved, setPlanApproved] = useState(false);

  // Время фиксируем после маунта: иначе SSR и клиент посчитают «дни в стадии» (SALES-43) по
  // разным часам и React ругнётся на расхождение гидрации. До маунта (now=null) бейджи дней
  // и фильтр висяков ничего не показывают. Заодно тянем актуальный справочник причин отказа.
  useEffect(() => {
    queueMicrotask(() => setNow(Date.now()));
    void fetchLossReasons().then((reasons) => {
      if (reasons.length) setLossReasons(reasons);
    });
    // П1: восстановить состояние стрелки «Ещё показатели».
    try {
      if (localStorage.getItem("deals_kpis_more") === "1") setMoreKpis(true);
    } catch {}
    // П2: согласован ли план текущего месяца (для подзаголовка шапки скорборда).
    const d = new Date();
    const periodKey = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    void fetchPlans({ period_type: "month", period_key: periodKey }).then((plans) => {
      if (plans.some((p) => p.status === "approved")) setPlanApproved(true);
    });
    // A: менеджеры для «Чья доска» (кэш общий с меню карточки — второй раз не фетчится).
    void fetchManagersCached().then(setManagers);
  }, []);

  /** A: переключатель «Чья доска» и секция «Ответственный» в FiltersMenu — две ручки
   *  одного URL-параметра `?owner=` (источник истины — URL, как у funnel/priority). */
  function setOwnerParam(name: string | null) {
    const next = new URLSearchParams(searchParams.toString());
    if (name) next.set("owner", name);
    else next.delete("owner");
    router.replace(`${pathname}?${next.toString()}`);
  }

  function toggleMoreKpis() {
    // Запись вне updater-а: side-effect внутри setState под StrictMode дёргается дважды.
    const next = !moreKpis;
    setMoreKpis(next);
    try {
      localStorage.setItem("deals_kpis_more", next ? "1" : "0");
    } catch {}
  }

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));
  // Стабильный id для DndContext: dnd-kit иначе сидит aria-describedby модульным
  // счётчиком, который расходится между SSR и клиентом → ошибка гидрации. useId
  // даёт одинаковое значение на сервере и при гидрации.
  const dndId = useId();

  function handleDragStart(e: DragStartEvent) {
    const id = String(e.active.id);
    setActiveDeal(stages.flatMap((s) => s.deals).find((d) => d.id === id) ?? null);
  }

  function findDeal(id: string): { deal: Deal; stageId: string; combined?: boolean } | null {
    for (const s of stages) {
      const deal = s.deals.find((d) => d.id === id);
      if (deal) return { deal, stageId: s.id };
    }
    // «Все вместе» + группировка «По датам»/«Список» (см. рендер ниже) сплющивают все секции
    // в один список — сделка может жить только в combinedStages, не в основном `stages`.
    if (combinedStages) {
      for (const sec of combinedStages) {
        for (const s of sec.stages) {
          const deal = s.deals.find((d) => d.id === id);
          if (deal) return { deal, stageId: s.id, combined: true };
        }
      }
    }
    return null;
  }

  /** Открыть модалку отказа (SALES-40): причина обязательна, без неё сделку не слить. */
  function openLose(dealId: string) {
    const found = findDeal(dealId);
    if (!found) return;
    setLosing({ dealId, label: `№ ${found.deal.number} · ${found.deal.company}` });
  }

  /** Подтвердить отказ: помечаем сделку (причина/коммент/вероятность 0) и двигаем в «отказ». */
  function confirmLose(reasonCode: string, comment?: string) {
    const dealId = losing?.dealId;
    if (!dealId) return;
    setStages((prev) => {
      const tagged = prev.map((s) => ({
        ...s,
        deals: s.deals.map((d) =>
          d.id === dealId ? { ...d, lostReasonCode: reasonCode, lostComment: comment, probability: 0 } : d,
        ),
      }));
      return moveDealToStage(tagged, dealId, "lost");
    });
    void loseDeal(dealId, reasonCode, comment);
    setLosing(null);
  }

  function handleDragEnd(e: DragEndEvent) {
    setActiveDeal(null);
    const dealId = String(e.active.id);
    const targetStage = e.over ? String(e.over.id) : null;
    if (!targetStage) return;

    // Перетаскивание в «отказ» обязано спросить причину (SALES-40): не двигаем и не дёргаем
    // бэк, пока менеджер не выберет причину в модалке. Внутри самой колонки «отказ» — ничего.
    if (targetStage === "lost") {
      const found = findDeal(dealId);
      if (found && found.stageId !== "lost") openLose(dealId);
      return;
    }

    const found = findDeal(dealId); // снимок ДО переноса — проверить, был ли уже шаг (D)

    setStages((prev) => moveDealToStage(prev, dealId, targetStage));

    void updateDealStage(dealId, targetStage);

    // D (слайс 4): целевая стадия открыта и у сделки ещё нет шага — подставляем дефолтный
    // пресет стадии (сделку с уже назначенным шагом не перетираем).
    if (found?.deal && shouldAutoAssignNextStep(found.deal, targetStage)) {
      handleNextStep(dealId, autoNextStepPatch(targetStage));
    }
  }

  async function handleCreate(input: DealInput): Promise<boolean> {
    const created = await createDeal(input);
    if (!created) return false;
    if (modalStages) {
      // Создано из секции «Все вместе» — её доска живёт в локальном стейте FunnelSection
      // (не в `stages`), оптимистично туда не дотянуться отсюда; SSR-рефреш подтянет секцию.
      router.refresh();
    } else {
      setStages((prev) =>
        recomputeStages(prev.map((s) => (s.id === input.stage ? { ...s, deals: [...s.deals, created] } : s))),
      );
    }
    setModalOpen(false);
    return true;
  }

  async function handleLog(kpiKey: string) {
    if (!(await logActivity(kpiKey))) return;
    const fresh = await getKpis(period);
    if (fresh.length) setKpis(fresh);
  }

  async function handlePeriod(p: string) {
    setPeriod(p);
    const fresh = await getKpis(p);
    if (fresh.length) setKpis(fresh);
  }

  function openModal(stageId: string, sectionStages?: Stage[]) {
    setModalStage(stageId);
    setModalStages(sectionStages ?? null);
    setModalOpen(true);
  }

  // Поиск (номер/контрагент/описание) + приоритет + «только висяки» (SALES-43) +
  // «действие сегодня/завтра». Общая функция — те же фильтры действуют и на секции
  // «Все вместе» (иначе тулбар в комбинированном виде был бы декорацией).
  // useMemo обязателен: FunnelSection ресетит свой локальный drag&drop-стейт по ссылке
  // initialStages — без мемоизации любой ре-рендер (клик по карточке, открытие звонка)
  // пересоздавал бы filteredCombined и «отбрасывал» перетащенную карточку в старую колонку.
  const q = query.trim().toLowerCase();
  const { filteredStages, filteredCombined } = useMemo(() => {
    const applyDealFilters = (s: Stage): Stage => {
      let deals = s.deals;
      if (q) {
        deals = deals.filter((d) =>
          `${d.number} ${d.company} ${d.description ?? ""}`.toLowerCase().includes(q),
        );
      }
      if (priority) deals = deals.filter((d) => d.priority === priority);
      if (ownerFilter) deals = deals.filter((d) => d.owner === ownerFilter);
      // «Внимание» (FiltersMenu): просроченный шаг / нет шага — только по открытым стадиям
      // (та же логика, что у чипов actBucket/«нет шага» на карточке).
      if (attn === "overdue") {
        deals = deals.filter(
          (d) => !isClosedStageId(s.id) && now != null && dateBucketId(d, now) === "overdue",
        );
      } else if (attn === "no_step") {
        deals = deals.filter((d) => !isClosedStageId(s.id) && !d.nextStep && !d.todo);
      } else if (attn === "revive") {
        // «Реанимировать»: условные отказы старше порога без касания (reviveDays, board.ts).
        deals = deals.filter((d) => now != null && reviveDays(d, s.id, now) != null);
      }
      if (stuckOnly) deals = deals.filter((d) => now != null && isStuck(d, s.id, now));
      if (actFilter) deals = deals.filter((d) => now != null && dateBucketId(d, now) === actFilter);
      return { ...s, deals, count: deals.length, sum: deals.reduce((a, d) => a + d.amount, 0) };
    };
    return {
      filteredStages: stages.map(applyDealFilters),
      filteredCombined: combinedStages?.map((sec) => ({
        ...sec,
        stages: sec.stages.map(applyDealFilters),
      })),
    };
  }, [stages, combinedStages, q, priority, ownerFilter, attn, stuckOnly, now, actFilter]);

  // Слайс 5 (A): очередь «Фокус дня» — строится от ТЕКУЩЕЙ отфильтрованной основной доски
  // (filteredStages), поэтому «Чья доска» (слайс 3) и остальные фильтры автоматически дают
  // «мой фокус» без отдельной логики. ponytail: в «Все вместе» секции («Все вместе»,
  // filteredCombined) держат свой стейт ВНУТРИ FunnelSection (не поднят наверх, см.
  // FunnelSection.stages) — точная объединённая очередь потребовала бы либо поднять их
  // стейт сюда, либо звать focusQueue на секцию и мержить бакет-в-бакет (порядок важнее
  // конкатенации). Пока в «Все вместе» фокус показывает только `filteredStages` (первая
  // секция) — тот же охват, что уже использует PipelineRow выше. Апгрейд — при переносе
  // per-section стейта наверх.
  const focusResult = useMemo(() => focusQueue(filteredStages, now), [filteredStages, now]);

  const reasonByCode = new Map(lossReasons.map((r) => [r.code, r.title]));

  /** «Просрочено»/«Сегодня»/«Завтра» для чипа срочности карточки: только по открытым
   *  сделкам — у выигранных/проигранных «дедлайн следующего шага» смысла не имеет. */
  function actBucketFor(deal: Deal, closed: boolean): "overdue" | "today" | "tomorrow" | null {
    if (closed || now == null) return null;
    const b = dateBucketId(deal, now);
    return b === "overdue" || b === "today" || b === "tomorrow" ? b : null;
  }

  /** Оптимистичный патч полей сделки из меню карточки (⋯) + fire-and-forget PATCH бэку.
   *  Имена полей совпадают с DealUpdate бэка (owner/priority/starred) — шлём как есть. */
  function patchDealFields(dealId: string, fields: DealCardPatch) {
    setStages((prev) =>
      prev.map((s) => ({
        ...s,
        deals: s.deals.map((d) => (d.id === dealId ? { ...d, ...fields } : d)),
      })),
    );
    void updateDeal(dealId, fields);
  }

  /** Слайс 4 («след. шаг в 2 клика»): назначить/очистить следующий шаг — из композера
   *  карточки (ручной выбор) или авто-назначения при смене стадии (handleDragEnd/drawer).
   *  Гасим legacy todo/actionDate/actionTime — иначе dealStepText (board.ts) отдал бы
   *  приоритет старому todo поверх нового next_step. Оптимистично, fire-and-forget PATCH. */
  function handleNextStep(dealId: string, patch: NextStepPatch) {
    setStages((prev) =>
      prev.map((s) => ({
        ...s,
        deals: s.deals.map((d) =>
          d.id === dealId
            ? {
                ...d,
                nextStep: patch.text ?? undefined,
                nextStepAt: patch.atISO ?? undefined,
                todo: undefined,
                actionDate: undefined,
                actionTime: undefined,
              }
            : d,
        ),
      })),
    );
    void updateDeal(dealId, { next_step: patch.text, next_step_at: patch.atISO });
  }

  /** Вычислить бейджи/плашки Сделки 2.0 для карточки по её стадии и текущему времени. */
  function cardExtras(deal: Deal, stageId: string): CardExtras {
    const code = deal.lostReasonCode;
    const closed = isClosedStageId(stageId);
    const hasNoStep = !closed && !deal.nextStep && !deal.todo;
    // Слайс 5 (C): первая стадия ТЕКУЩЕГО списка = стадия новой заявки (тот же критерий
    // «первая стадия списка», что и focusQueue в board.ts — согласовано намеренно).
    const isFirstStage = filteredStages[0]?.id === stageId;
    return {
      actBucket: actBucketFor(deal, closed),
      noStep: hasNoStep,
      noTouchDays:
        hasNoStep && isFirstStage && now != null ? (daysInStage(deal.stageChangedAt, now) ?? 0) : null,
      reviveDays: now != null ? reviveDays(deal, stageId, now) : null,
      days: now != null ? daysInStage(deal.stageChangedAt, now) : null,
      // FIX-2: isStuck (board.ts) сам гейтит закрытые стадии (won/lost/cond_lost) — единый
      // хелпер для карточки, списка, счётчика колонки, фильтра «Висяки» и PipelineRow.
      stuck: now != null && isStuck(deal, stageId, now),
      probability: probabilityFor(deal, stageId),
      weighted: weightedAmount(deal, stageId),
      lostReasonTitle: code ? (reasonByCode.get(code) ?? code) : undefined,
      wonResult: stageId === "won",
      onLose: stageId === "won" || stageId === "lost" ? undefined : () => openLose(deal.id),
      onCall: () => setCallDeal(deal),
      onUpdate: (fields) => patchDealFields(deal.id, fields),
      stageId,
      onNextStep: (patch) => handleNextStep(deal.id, patch),
    };
  }
  // «Все вместе» + «По датам»/«Список» (см. рендер ниже) сплющивают ВСЕ секции воронок —
  // не только текущую `stages` (первая секция из SSR) — иначе список/бакеты дат теряли бы
  // сделки остальных воронок. Id стадий канонические и общие для всех воронок (sales-stages.ts),
  // поэтому probabilityFor/weightedAmount/STAGE_BY_ID работают одинаково в обоих случаях.
  const flatDeals = filteredCombined
    ? filteredCombined.flatMap((sec) =>
        sec.stages.flatMap((s) =>
          s.deals.map((d) => ({ deal: d, stageTitle: `${sec.title} · ${s.title}`, stageId: s.id })),
        ),
      )
    : filteredStages.flatMap((s) => s.deals.map((d) => ({ deal: d, stageTitle: s.title, stageId: s.id })));

  /** Бейджи карточки для секций «Все вместе»: та же формула, без «Отказ»-кнопки —
   *  причина отказа собирается через ту же модалку только на основной (не-комбинированной)
   *  доске; в комбинированном виде drag в терминальную колонку двигает сделку напрямую
   *  (ponytail: единый confirmLose-гейт для комбинированного вида — если понадобится). */
  function combinedCardExtras(deal: Deal, stageId: string, sectionStages: Stage[]): CardExtras {
    const code = deal.lostReasonCode;
    const wonId = sectionStages.find((s) => s.id.endsWith("won"))?.id;
    const closed = isClosedStageId(stageId);
    const hasNoStep = !closed && !deal.nextStep && !deal.todo;
    // Слайс 5 (C): первая стадия ЭТОЙ секции (не всей доски) — та же семантика, что cardExtras.
    const isFirstStage = sectionStages[0]?.id === stageId;
    return {
      actBucket: actBucketFor(deal, closed),
      noStep: hasNoStep,
      noTouchDays:
        hasNoStep && isFirstStage && now != null ? (daysInStage(deal.stageChangedAt, now) ?? 0) : null,
      reviveDays: now != null ? reviveDays(deal, stageId, now) : null,
      days: now != null ? daysInStage(deal.stageChangedAt, now) : null,
      // FIX-2: гейт закрытых стадий живёт в самом isStuck — формула та же, что в cardExtras.
      stuck: now != null && isStuck(deal, stageId, now),
      probability: probabilityFor(deal, stageId),
      weighted: weightedAmount(deal, stageId),
      lostReasonTitle: code ? (reasonByCode.get(code) ?? code) : undefined,
      wonResult: stageId === wonId,
      onCall: () => setCallDeal(deal),
      stageId,
      // onUpdate/onNextStep добавляет FunnelSection (доска секции — её локальный стейт).
    };
  }

  return (
    <>
      {/* pr увеличен против стандартных p-6: плавающая рейка чатов/уведомлений (AppShell,
          absolute right-0, w-[68px], во ВСЮ высоту экрана, не резервирует место в layout)
          перекрывает крайние ~44px контента на ЛЮБОЙ ширине окна (main всегда тянется до
          истинного правого края) — метрики П1 (8 ячеек) упирались в неё последней ячейкой
          «Средний чек». Тот же приём уже применён на /crm/deals/analytics. */}
      <main className="flex-1 overflow-auto p-6 pr-20">
        {demoData && (
          <div
            role="status"
            className="mb-3 flex items-center gap-2 rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2 text-[12.5px] font-semibold text-amber-900 dark:bg-amber-500/10 dark:text-amber-200"
          >
            ⚠️ Демо-данные: backend недоступен, показана демонстрационная доска — изменения не сохранятся.
          </div>
        )}
        {/* Тулбар (поиск/переключатель ЮЛ/«Стадии»/«План»/«Фильтры») переехал в шапку
            страницы и в строки скорборда/воронок (решение оператора) — тут пусто. */}

        <PlanBanner now={now} />

        {/* План / Факт по периодам: первичный ряд = 8 метрик макета (П1), бейдж темпа +
            подзаголовок + pulse (П2), остальные метрики — под стрелкой «Ещё N». Не sticky
            (решение оператора): скорборд прокручивается вместе с доской, не «ездит». */}
        {(() => {
          const elapsed = now != null ? periodElapsed(now, period) : null;
          const kpiByKey = new Map(kpis.map((k) => [k.id, k]));
          const secondary = kpis.filter((k) => !PRIMARY_CELLS.some((c) => c.key === k.id));
          // Бейдж темпа (П2): выполнение headline-метрики против прошедшего времени периода.
          const ship = kpiByKey.get("ship_plan");
          const elapsedPct = elapsed != null ? Math.round(elapsed * 100) : null;
          let pace: { cls: string; text: string } | null = null;
          if (ship && ship.target > 0 && elapsedPct != null && elapsed! >= 0.05) {
            const diff = ship.percent - elapsedPct;
            pace =
              diff >= 5
                ? { cls: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300", text: `🟢 Опережаем график на ${diff} п.п.` }
                : diff <= -5
                  ? { cls: "bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300", text: `🔴 Отстаём на ${-diff} п.п.` }
                  : { cls: "bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300", text: "🟡 Идём в графике" };
          }
          // Chip прогноза закрытия (П3) — run-rate по headline.
          let chip: string | null = null;
          if (ship && ship.target > 0 && elapsed != null && elapsed >= 0.1) {
            const projPct = Math.round((ship.value / elapsed / ship.target) * 100);
            chip = `Закроем ${PERIOD_ACC[period] ?? period} на ~${projPct}% плана`;
          }
          // Гэп до плана (слайс 3, D): план выручки минус факт; ≈сделок — по среднему чеку
          // (факт avg_deal → плановый avg_deal → средний чек won-сделок доски). Данные уже
          // пришли для скорборда — новых бэк-вызовов нет. Нет плана/чека → honest-empty.
          let planGap: { gap: number; deals: number; avg: number } | null = null;
          if (ship && ship.target > 0 && ship.target > ship.value) {
            const gap = ship.target - ship.value;
            const avgKpi = kpiByKey.get("avg_deal");
            const wonDeals = stages.find((s) => s.id === "won")?.deals ?? [];
            const wonAvg = wonDeals.length
              ? wonDeals.reduce((a, d) => a + d.amount, 0) / wonDeals.length
              : 0;
            const avg =
              avgKpi && avgKpi.value > 0
                ? avgKpi.value
                : avgKpi && avgKpi.target > 0
                  ? avgKpi.target
                  : wonAvg;
            if (avg > 0) planGap = { gap, deals: Math.ceil(gap / avg), avg: Math.round(avg) };
          }
          const sub = periodSubLabel(period, now);
          return (
            <>
              <section className="mt-5">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2 pt-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_0_4px_rgba(34,197,94,.15)]"
                      aria-hidden
                    />
                    <h2 className="font-semibold text-ink">План / Факт</h2>
                    {/* «План» (планирование продавца/РОП) — в одну линию правее заголовка
                        (решение оператора; раньше жил в верхнем тулбаре). */}
                    <Link
                      href="/crm/deals/planning"
                      className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3.5 py-2 text-sm font-medium text-muted hover:bg-sunken hover:text-ink"
                    >
                      План
                    </Link>
                    {sub && (
                      <span className="text-[12px] text-muted">
                        — {sub}
                        {planApproved && " · план продаж согласован РОПом"}
                      </span>
                    )}
                    {pace && (
                      <span
                        className={clsx(
                          "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] font-semibold",
                          pace.cls,
                        )}
                      >
                        {pace.text}
                        {elapsedPct != null && (
                          <span className="font-normal opacity-75">· прошло {elapsedPct}% периода</span>
                        )}
                      </span>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center justify-end gap-2">
                    {secondary.length > 0 && (
                      <button
                        onClick={toggleMoreKpis}
                        className="rounded-lg border border-line bg-surface px-2.5 py-1 text-xs font-medium text-muted hover:text-ink"
                      >
                        {moreKpis ? "Свернуть ▴" : `Ещё ${secondary.length} показателей ▾`}
                      </button>
                    )}
                    {/* Период — выпадающий список (решение оператора: раньше группа кнопок). */}
                    <select
                      aria-label="Период"
                      value={PERIODS.some((p) => p.key === period) ? period : ""}
                      onChange={(e) => handlePeriod(e.target.value)}
                      className="rounded-lg border border-line bg-surface px-2 py-1 text-xs font-medium text-ink outline-none"
                    >
                      {PERIODS.map((p) => (
                        <option key={p.key} value={p.key}>
                          {p.label}
                        </option>
                      ))}
                    </select>
                    {/* Произвольный месяц+год (period=YYYY-MM — GET /sales/kpis его понимает). */}
                    <input
                      type="month"
                      value={MONTH_PERIOD_RE.test(period) ? period : ""}
                      onChange={(e) => e.target.value && handlePeriod(e.target.value)}
                      title="Показатели за выбранный месяц"
                      aria-label="Выбрать месяц и год"
                      className={clsx(
                        "rounded-lg border px-2 py-1 text-xs font-medium outline-none",
                        MONTH_PERIOD_RE.test(period)
                          ? "border-accent bg-accent-soft text-accent-ink"
                          : "border-line bg-surface text-muted",
                      )}
                    />
                    {/* «Только висяки» + «Аналитика» перенесены из тулбара на строку заголовка
                        скорборда — левее CTA «Создать сделку», в одну линию (решение оператора). */}
                    <button
                      onClick={() => setStuckOnly((v) => !v)}
                      className={clsx(
                        "inline-flex items-center gap-2 rounded-lg border bg-surface px-3.5 py-2 text-sm font-medium hover:bg-sunken",
                        stuckOnly ? "border-amber-400 text-amber-700" : "border-line text-muted",
                      )}
                    >
                      <Clock size={16} /> Висяки
                    </button>
                    <Link
                      href="/crm/deals/analytics"
                      className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface px-3.5 py-2 text-sm font-medium text-muted hover:bg-sunken hover:text-ink"
                    >
                      Аналитика
                    </Link>
                    {/* Первичный CTA доски перенесён из тулбара на строку заголовка скорборда
                        (решение оператора «в одну строку» — эффективнее по вертикали). */}
                    <button
                      onClick={() => openModal(stages[0]?.id ?? "new")}
                      className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-accent-ink"
                    >
                      <Plus size={16} /> Создать сделку
                    </button>
                  </div>
                </div>
                <div className="overflow-hidden rounded-2xl bg-line shadow-card">
                  {/* overflow-x-auto + min-w — страховка: при недостаточной реальной ширине
                      (DPI-масштаб браузера/встроенные панели съедают больше px, чем кажется
                      по разрешению) колонки не сжимаются до нечитаемости и не «пропадают» —
                      появляется горизонтальный скролл, ничего не теряется молча. В обычном
                      случае (места хватает) скролл не активируется, выглядит как раньше. */}
                  <div className="overflow-x-auto thin-scroll">
                    {/* Первичный ряд — 8 метрик макета в его порядке; на xl одна строка,
                        первая колонка (headline) шире, как sb-row эталона. */}
                    <div className="grid gap-px sm:grid-cols-2 lg:grid-cols-4 xl:min-w-[880px] xl:grid-cols-[minmax(0,1.5fr)_repeat(7,minmax(0,1fr))]">
                      {PRIMARY_CELLS.map((cell) => {
                        const kpi = kpiByKey.get(cell.key);
                        if (!kpi) return <PlanFactPlaceholder key={cell.key} label={cell.label} />;
                        const coldCalls = cell.key === "calls_all" ? kpiByKey.get("calls_cold") : undefined;
                        return (
                          <PlanFactCell
                            key={cell.key}
                            kpi={kpi}
                            fmt={fmt}
                            elapsed={elapsed}
                            onLog={() => handleLog(kpi.id)}
                            label={cell.label}
                            headline={cell.headline}
                            subnote={coldCalls ? `из них ${coldCalls.value} хол.` : undefined}
                          />
                        );
                      })}
                    </div>
                    {/* Второй ряд (П1): тот же вид ячеек, раскрывается стрелкой. */}
                    {moreKpis && secondary.length > 0 && (
                      <div className="grid gap-px border-t border-dashed border-line sm:grid-cols-2 lg:grid-cols-4 xl:min-w-[880px] xl:grid-cols-8">
                        {secondary.map((kpi) => (
                          <PlanFactCell
                            key={kpi.id}
                            kpi={kpi}
                            fmt={fmt}
                            elapsed={elapsed}
                            onLog={() => handleLog(kpi.id)}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </section>

              <PipelineRow stages={stages} now={now} fmt={fmt} chip={chip} planGap={planGap} />
            </>
          );
        })()}

        {/* Ряд над канбаном (мокап): слева — поиск + воронки + быстрые фильтры дат «в одну
            линию по стадиям»; справа — группировка/вид. Поиск/воронки/чипы жили в верхнем
            тулбаре, но по решению оператора вынесены сюда, вплотную к колонкам. */}
        <div className="mt-5 flex flex-wrap items-center gap-2">
          <div className="flex flex-wrap items-center gap-2">
            {/* Поиск сделок — левее «Все вместе», в одну строку (решение оператора). */}
            <div className="relative w-64 shrink-0">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Поиск сделок..."
                className="w-full rounded-lg border border-line bg-surface py-2 pl-9 pr-3 text-sm text-ink outline-none placeholder:text-faint focus:border-accent"
              />
            </div>
            {funnelTabs}
            {/* A (слайс 3): «Чья доска» — сегментированный переключатель по ответственному.
                Та же ручка ?owner=, что у секции «Ответственный» в FiltersMenu (шапка страницы):
                две ручки одного URL-параметра. Продавец смотрит и свою, и чужую доску. */}
            {managers.length > 0 && (
              <div
                role="group"
                aria-label="Чья доска"
                className="flex items-center gap-0.5 overflow-x-auto rounded-lg border border-line bg-surface p-0.5"
              >
                <button
                  onClick={() => setOwnerParam(null)}
                  title="Сделки всех менеджеров"
                  className={clsx(
                    "rounded-md px-2.5 py-1.5 text-[12.5px] font-medium whitespace-nowrap",
                    !ownerFilter ? "bg-accent-soft text-accent-ink" : "text-muted hover:text-ink",
                  )}
                >
                  👥 Все
                </button>
                {managers.map((m) => (
                  <button
                    key={m.name}
                    onClick={() => setOwnerParam(ownerFilter === m.name ? null : m.name)}
                    title={`Доска менеджера: ${m.name}`}
                    className={clsx(
                      "rounded-md px-2.5 py-1.5 text-[12.5px] font-medium whitespace-nowrap",
                      ownerFilter === m.name
                        ? "bg-accent-soft text-accent-ink"
                        : "text-muted hover:text-ink",
                    )}
                  >
                    {m.name}
                  </button>
                ))}
              </div>
            )}
            {/* B (слайс 5): «Фокус дня» — упорядоченная очередь «что делать сейчас» вместо
                сканирования колонок. Бейдж = total ДО обрезки cap (реальная потребность),
                красный — в очереди есть что-то горящее (severity=crit). */}
            <button
              type="button"
              onClick={() => setFocusOpen(true)}
              title="Фокус дня — упорядоченная очередь приоритетных сделок"
              className={clsx(
                "inline-flex items-center gap-1.5 rounded-lg border bg-surface px-3.5 py-2 text-sm font-medium hover:bg-sunken",
                focusOpen ? "border-accent text-accent-ink" : "border-line text-muted",
              )}
            >
              🎯 Фокус дня
              {focusResult.total > 0 && (
                <span
                  className={clsx(
                    "rounded-full px-1.5 py-0.5 text-[11px] font-bold",
                    focusResult.items.some((i) => i.severity === "crit")
                      ? "bg-red-600 text-white"
                      : "bg-accent-soft text-accent-ink",
                  )}
                >
                  {focusResult.total}
                </span>
              )}
            </button>
            {/* Быстрый фильтр «действие сегодня/завтра» (мокап actSeg); повторный клик — снять */}
            {(["today", "tomorrow"] as const).map((k) => (
              <button
                key={k}
                onClick={() => setActFilter((v) => (v === k ? null : k))}
                title="Показать сделки, по которым действие сегодня/завтра"
                className={clsx(
                  "inline-flex items-center gap-2 rounded-lg border bg-surface px-3.5 py-2 text-sm font-medium hover:bg-sunken",
                  actFilter === k
                    ? k === "today"
                      ? "border-red-400 text-red-700 dark:text-red-300"
                      : "border-orange-400 text-orange-700 dark:text-orange-300"
                    : "border-line text-muted",
                )}
              >
                {k === "today" ? "🔴 На сегодня" : "🟠 На завтра"}
              </button>
            ))}
          </div>
          {/* Группировка/вид — видны и в «Все вместе» (эталон sales-board-mockup.html держит
              их всегда): «По датам»/«Список» там выходят из стопки секций в плоский список
              (см. ветки рендера ниже), «По стадиям»+«Канбан» — обратно в стопку воронок. */}
          <div className="ml-auto flex items-center gap-2">
              {/* П4: группировка канбана — по стадиям / по датам следующего действия. */}
              {view === "board" && (
                <div className="flex items-center gap-0.5 rounded-lg border border-line bg-surface p-0.5">
                <button
                  onClick={() => setGroupBy("stage")}
                  title="По стадиям"
                  aria-label="По стадиям"
                  className={clsx(
                    "rounded-md p-1.5",
                    groupBy === "stage" ? "bg-accent-soft text-accent-ink" : "text-faint hover:text-muted",
                  )}
                >
                  <LayoutList size={14} />
                </button>
                <button
                  onClick={() => setGroupBy("dates")}
                  title="По датам действий"
                  aria-label="По датам действий"
                  className={clsx(
                    "rounded-md p-1.5",
                    groupBy === "dates" ? "bg-accent-soft text-accent-ink" : "text-faint hover:text-muted",
                  )}
                >
                  <Calendar size={14} />
                </button>
              </div>
            )}
            <div className="flex items-center gap-0.5 rounded-lg border border-line bg-surface p-0.5">
              <button
                onClick={() => setView("board")}
                title="Канбан"
                className={clsx(
                  "rounded-md p-1.5",
                  view === "board" ? "bg-accent-soft text-accent-ink" : "text-faint hover:text-muted",
                )}
              >
                <LayoutGrid size={16} />
              </button>
              <button
                onClick={() => setView("list")}
                title="Список"
                className={clsx(
                  "rounded-md p-1.5",
                  view === "list" ? "bg-accent-soft text-accent-ink" : "text-faint hover:text-muted",
                )}
              >
                <List size={16} />
              </button>
            </div>
          </div>
        </div>

        {view === "board" && groupBy === "dates" ? (
          /* П4: группировка по датам действий (next_step_at) — честные бакеты, без drag&drop
           * (перенос между бакетами = смена next_step_at, не текущее действие карточки).
           * Как в эталоне (sales-board-mockup.html): группировка выходит из стопки секций
           * «Все вместе» в один плоский срез — flatDeals уже учитывает combinedStages. */
          <div className="mt-3 flex gap-4 overflow-x-auto pb-2 thin-scroll">
            {groupByDateBucket(flatDeals.map((f) => f.deal), now ?? Date.now()).map((bucket) => (
              <DateColumn key={bucket.id} bucket={bucket} fmt={fmt}>
                {bucket.deals.map((deal) => {
                  const found = findDeal(deal.id);
                  const extras = cardExtras(deal, found?.stageId ?? "new");
                  // Сделка из секции «Все вместе» живёт не в `stages` — Lose-модалка (openLose)
                  // двигает только `stages`, локально не отразит перенос для combined-сделки.
                  if (found?.combined) extras.onLose = undefined;
                  return (
                    <StaticDealCard
                      key={deal.id}
                      deal={deal}
                      extras={extras}
                      fmt={fmt}
                      onPreview={setPreviewDeal}
                      onOpen={(d) => router.push(`/crm/deals/${d.id}`)}
                    />
                  );
                })}
              </DateColumn>
            ))}
          </div>
        ) : view === "list" ? (
          /* Список — плоский срез (работает и для «Все вместе»: flatDeals уже включает
             combinedStages при необходимости, см. вычисление выше). */
          <div className="mt-3 overflow-hidden rounded-xl bg-surface shadow-card">
            <table className="w-full text-sm">
              <thead className="border-b border-line text-left text-xs text-muted">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Номер</th>
                  <th className="px-4 py-2.5 font-medium">Контрагент</th>
                  <th className="px-4 py-2.5 font-medium">Описание</th>
                  <th className="px-4 py-2.5 font-medium">Стадия</th>
                  <th className="px-4 py-2.5 text-right font-medium">Вероятн.</th>
                  <th className="px-4 py-2.5 text-right font-medium">Сумма</th>
                  <th className="px-4 py-2.5 text-right font-medium">Взвешенно</th>
                </tr>
              </thead>
              <tbody>
                {flatDeals.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-6 text-center text-muted">
                      Сделок не найдено
                    </td>
                  </tr>
                )}
                {flatDeals.map(({ deal, stageTitle, stageId }) => {
                  // Вероятность/взвешенно — те же probabilityFor/weightedAmount и то же правило
                  // показа (prob > 0), что на карточке доски: won → ≈сумма, lost (0%) → «—».
                  // (isOpenStage — критерий для АГРЕГАТОВ: итог строки и колонки, не для per-deal.)
                  const prob = probabilityFor(deal, stageId);
                  const weighted = weightedAmount(deal, stageId);
                  // SALES-43/40: дни-в-стадии/висяк + причина отказа — те же значения, что cardExtras.
                  const days = now != null ? daysInStage(deal.stageChangedAt, now) : null;
                  const stuck = now != null && isStuck(deal, stageId, now);
                  const lostTitle = deal.lostReasonCode
                    ? (reasonByCode.get(deal.lostReasonCode) ?? deal.lostReasonCode)
                    : undefined;
                  return (
                  <tr key={deal.id} className="border-b border-line last:border-0 hover:bg-sunken">
                    <td className="px-4 py-2.5">
                      <Link href={`/crm/deals/${deal.id}`} className="font-medium text-accent-ink">
                        {deal.number}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-ink">{deal.company}</td>
                    <td className="px-4 py-2.5 text-muted">{deal.description}</td>
                    <td className="px-4 py-2.5">
                      <span className="inline-flex items-center gap-1.5 text-muted">
                        <span
                          className="h-1.5 w-1.5 rounded-full"
                          style={{ background: STAGE_BY_ID[stageId]?.color ?? "#64748B" }}
                          aria-hidden
                        />
                        {stageTitle}
                        {days != null && (
                          <span className={stuck ? "font-semibold text-amber-600" : "text-faint"}>
                            · {days} дн{stuck ? " · висяк" : ""}
                          </span>
                        )}
                      </span>
                      {lostTitle && (
                        <div className="mt-0.5 text-[11px] text-red-700">Причина: {lostTitle}</div>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-muted">{prob}%</td>
                    <td className="px-4 py-2.5 text-right font-medium text-ink">
                      {fmt(deal.amount)}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums font-semibold text-accent-ink">
                      {prob > 0 ? `≈ ${fmt(weighted)}` : "—"}
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : filteredCombined ? (
          /* «Все вместе» (мокап COMBINED): доска каждой воронки — своя секция, drag&drop
           * работает внутри секции (см. FunnelSection). Не дублирует канбан-логику —
           * переиспользует Column/DraggableDeal. */
          <>
            {filteredCombined.map((section) => (
              <FunnelSection
                key={section.code}
                title={section.title}
                color={FUNNEL_SECTION_COLOR[section.code] ?? "var(--accent)"}
                initialStages={section.stages}
                fmt={fmt}
                now={now}
                cardExtras={combinedCardExtras}
                onPreview={setPreviewDeal}
                onOpen={(d) => router.push(`/crm/deals/${d.id}`)}
                onAddDeal={openModal}
              />
            ))}
          </>
        ) : (
          /* Канбан с drag&drop */
          <DndContext id={dndId} sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
            <div className="mt-3 flex gap-4 overflow-x-auto pb-2 thin-scroll">
              {filteredStages.map((stage) => (
                <Column
                  key={stage.id}
                  stage={stage}
                  fmt={fmt}
                  stuckCount={
                    now == null ? 0 : stage.deals.filter((d) => isStuck(d, stage.id, now)).length
                  }
                  onAdd={() => openModal(stage.id)}
                >
                  {/* B (слайс 3): порядок «деньги × срочность» — sortDealsForBoard (board.ts). */}
                  {sortDealsForBoard(stage.deals, stage.id, now).map((deal) => (
                    <DraggableDeal
                      key={deal.id}
                      deal={deal}
                      extras={cardExtras(deal, stage.id)}
                      fmt={fmt}
                      onPreview={setPreviewDeal}
                      onOpen={(d) => router.push(`/crm/deals/${d.id}`)}
                    />
                  ))}
                </Column>
              ))}
            </div>
            <DragOverlay>
              {activeDeal ? (
                <div className="w-[280px] rotate-2">
                  <DealCard deal={activeDeal} fmt={fmt} />
                </div>
              ) : null}
            </DragOverlay>
          </DndContext>
        )}

        {/* Итоги — по выбранной воронке; в «Все вместе» единой суммы по разнородным
            воронкам нет (won/lost — разные коды на секцию), поэтому блок скрыт. */}
        {!combinedStages && <FunnelTotals data={computeFunnel(filteredStages)} fmt={fmt} />}
      </main>

      {modalOpen && (
        <CreateDealModal
          stages={modalStages ?? stages}
          defaultStage={modalStage}
          onClose={() => setModalOpen(false)}
          onCreate={handleCreate}
        />
      )}

      {losing && (
        <LoseDealModal
          dealLabel={losing.label}
          reasons={lossReasons}
          onCancel={() => setLosing(null)}
          onConfirm={confirmLose}
        />
      )}

      {/* Слайс 5 (B): панель «Фокус дня» — клик по элементу очереди закрывает панель и
          открывает тот же drawer-preview, что и клик по карточке на доске. */}
      <FocusPanel
        open={focusOpen}
        onClose={() => setFocusOpen(false)}
        result={focusResult}
        stageTitle={(stageId) => filteredStages.find((s) => s.id === stageId)?.title ?? stageId}
        fmt={fmt}
        onSelectDeal={(deal) => {
          setFocusOpen(false);
          setPreviewDeal(deal);
        }}
      />

      {/* Drawer-preview сделки: открывается single-click по карточке на доске.
          Цель — работа из канбана без проваливания в полную карточку: stage-mover,
          inline next-step, быстрая задача, ChannelButtons, Win/Lose. */}
      <DealDrawerPreview
        deal={previewDeal}
        stages={stages}
        onClose={() => setPreviewDeal(null)}
        onMoveStage={(dealId, stageId) => {
          if (stageId === "lost") {
            // Drawer-Lose открывает модалку причины (как drag в колонку «отказ»).
            openLose(dealId);
            return;
          }
          const found = stages.flatMap((s) => s.deals).find((d) => d.id === dealId) ?? null;
          setStages((prev) => moveDealToStage(prev, dealId, stageId));
          // Поддерживаем превью консистентным: если перенесли активный deal, обновляем ссылку
          setPreviewDeal((p) =>
            p && p.id === dealId
              ? (stages.flatMap((s) => s.deals).find((d) => d.id === dealId) ?? p)
              : p,
          );
          void updateDealStage(dealId, stageId);
          // D (слайс 4): авто-пресет, если целевая стадия открыта и шага ещё нет. ponytail:
          // previewDeal (снимок выше) не подхватит свежий next_step, пока drawer не переоткроют —
          // карточка на доске обновится сразу через handleNextStep→setStages.
          if (found && shouldAutoAssignNextStep(found, stageId)) {
            handleNextStep(dealId, autoNextStepPatch(stageId));
          }
        }}
        onUpdateFields={(dealId, fields) => {
          // Оптимистично патчим во всех колонках; UI-маппинг snake→camel для starred/next_step.
          const camel: Partial<Deal> = {};
          if ("next_step" in fields) camel.nextStep = String(fields.next_step ?? "");
          if ("starred" in fields) camel.starred = Boolean(fields.starred);
          if ("priority" in fields)
            camel.priority = fields.priority as Deal["priority"];
          setStages((prev) =>
            prev.map((s) => ({
              ...s,
              deals: s.deals.map((d) => (d.id === dealId ? { ...d, ...camel } : d)),
            })),
          );
          setPreviewDeal((p) => (p && p.id === dealId ? { ...p, ...camel } : p));
          void updateDeal(dealId, fields);
        }}
        onAddTask={(dealId, title) => {
          // Создаём fire-and-forget; в drawer'е список задач не показываем (он в полной карточке).
          void createDealTask(dealId, { title });
        }}
        onWin={(dealId) => {
          setStages((prev) => moveDealToStage(prev, dealId, "won"));
          void updateDealStage(dealId, "won");
          setPreviewDeal(null);
        }}
        onLose={(dealId) => {
          // Просим причину через ту же модалку, что и при drag-в-отказ.
          openLose(dealId);
          setPreviewDeal(null);
        }}
        onCall={(d) => setCallDeal(d)}
        now={now}
        reasonByCode={reasonByCode}
      />

      {/* Окно звонка по сделке — единый кокпит (скрипт сделки + подбор товара →
          позиции сделки реальным addDealItem). Тот же компонент, что и в лидах. */}
      <CallWindow
        context={
          callDeal
            ? {
                kind: "deal",
                dealId: callDeal.id,
                number: callDeal.number,
                company: callDeal.company,
              }
            : null
        }
        onClose={() => setCallDeal(null)}
      />
    </>
  );
}
