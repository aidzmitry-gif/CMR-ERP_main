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
import { Clock, LayoutGrid, List, Plus, Search, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { ChatsPanel } from "@/components/chats-panel";
import { FunnelTotals } from "@/components/funnel-totals";
import { CreateDealModal } from "@/components/kanban/create-deal-modal";
import { DealCard } from "@/components/kanban/deal-card";
import { CallWindow } from "@/components/calls/call-window";
import { DealDrawerPreview } from "@/components/kanban/deal-drawer-preview";
import { LoseDealModal } from "@/components/kanban/lose-deal-modal";
import { KpiCard } from "@/components/kpi-card";
import {
  createDeal,
  createDealTask,
  fetchLossReasons,
  getKpis,
  logActivity,
  loseDeal,
  updateDeal,
  updateDealStage,
  type DealInput,
} from "@/lib/api";
import {
  daysInStage,
  isStuck,
  LOSS_REASONS,
  moveDealToStage,
  probabilityFor,
  recomputeStages,
  stageWeightedSum,
  weightedAmount,
} from "@/lib/board";
import { formatMoney } from "@/lib/format";
import { computeFunnel } from "@/lib/funnel";
import type { Deal, Kpi, LossReason, Stage } from "@/lib/types";

/** Бейджи/плашки Сделки 2.0, вычисляемые для карточки из стадии и текущего времени. */
type CardExtras = {
  days: number | null;
  stuck: boolean;
  probability: number;
  weighted: number;
  lostReasonTitle?: string;
  wonResult: boolean;
  onLose?: () => void;
};

const PERIODS = [
  { key: "day", label: "День" },
  { key: "week", label: "Неделя" },
  { key: "month", label: "Месяц" },
  { key: "quarter", label: "Квартал" },
  { key: "year", label: "Год" },
];

function pluralDeals(n: number): string {
  const d10 = n % 10;
  const d100 = n % 100;
  if (d10 === 1 && d100 !== 11) return "сделка";
  if (d10 >= 2 && d10 <= 4 && (d100 < 12 || d100 > 14)) return "сделки";
  return "сделок";
}

function DraggableDeal({
  deal,
  extras,
  onPreview,
  onOpen,
}: {
  deal: Deal;
  extras: CardExtras;
  onPreview: (d: Deal) => void;
  onOpen: (d: Deal) => void;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: deal.id });
  // Click vs double-click: первый клик → setTimeout(230ms) → onPreview;
  // второй клик в окне таймера → clear + onOpen. Глушим встроенный <Link>
  // у DealCard через preventDefault — навигация идёт через router.push в onOpen.
  // Не мешаем клику по интерактивным дочерним (кнопка «Отказ», ChannelRow).
  const clickTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (clickTimer.current) clearTimeout(clickTimer.current);
  }, []);

  function handleClickCapture(e: React.MouseEvent) {
    const target = e.target as HTMLElement;
    if (target.closest("button")) return; // отказ-кнопка, иконки каналов — не глушим
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
      {...attributes}
      {...listeners}
      onClickCapture={handleClickCapture}
      className={isDragging ? "opacity-40" : ""}
    >
      <DealCard deal={deal} {...extras} />
    </div>
  );
}

function Column({
  stage,
  onAdd,
  children,
}: {
  stage: Stage;
  onAdd: () => void;
  children: React.ReactNode;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: stage.id });
  // Взвешенная сумма по колонке (SALES-44) — только для рабочих стадий с карточками.
  const showWeighted = stage.id !== "won" && stage.id !== "lost" && stage.deals.length > 0;
  return (
    <div className="flex w-[300px] shrink-0 flex-col gap-3">
      <div className="overflow-hidden rounded-xl bg-surface shadow-card">
        <div className="h-1" style={{ backgroundColor: stage.color }} />
        <div className="px-4 py-3">
          <div className="font-semibold text-ink">{stage.title}</div>
          <div className="mt-0.5 text-xs text-muted">
            {stage.count} {pluralDeals(stage.count)} · {formatMoney(stage.sum)}
          </div>
          {showWeighted && (
            <div className="mt-0.5 text-[11px] font-semibold text-accent-ink">
              взвешенно: {formatMoney(stageWeightedSum(stage))}
            </div>
          )}
        </div>
      </div>
      <div
        ref={setNodeRef}
        className={clsx(
          "flex min-h-20 flex-col gap-3 rounded-xl p-1 transition-colors",
          isOver && "bg-accent-soft ring-2 ring-accent",
        )}
      >
        {children}
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

export function DealsWorkspace({
  initialStages,
  initialKpis,
}: {
  initialStages: Stage[];
  initialKpis: Kpi[];
}) {
  const router = useRouter();
  const [stages, setStages] = useState<Stage[]>(initialStages);
  const [kpis, setKpis] = useState<Kpi[]>(initialKpis);
  const [period, setPeriod] = useState("day");
  const [activeDeal, setActiveDeal] = useState<Deal | null>(null);
  // single-click по сделке открывает drawer-preview (sales-card-expanded.html);
  // double-click уходит на /crm/deals/[id] (полная страница, sales-card-full.html).
  const [previewDeal, setPreviewDeal] = useState<Deal | null>(null);
  // callDeal = открыто окно звонка по этой сделке (тот же кокпит, что и у лида).
  const [callDeal, setCallDeal] = useState<Deal | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalStage, setModalStage] = useState<string>(initialStages[0]?.id ?? "new");
  const [query, setQuery] = useState("");
  const [priority, setPriority] = useState<string | null>(null);
  const [filterOpen, setFilterOpen] = useState(false);
  const [view, setView] = useState<"board" | "list">("board");
  const [stuckOnly, setStuckOnly] = useState(false);
  const [now, setNow] = useState<number | null>(null);
  const [lossReasons, setLossReasons] = useState<LossReason[]>(LOSS_REASONS);
  const [losing, setLosing] = useState<{ dealId: string; label: string } | null>(null);

  // Время фиксируем после маунта: иначе SSR и клиент посчитают «дни в стадии» (SALES-43) по
  // разным часам и React ругнётся на расхождение гидрации. До маунта (now=null) бейджи дней
  // и фильтр висяков ничего не показывают. Заодно тянем актуальный справочник причин отказа.
  useEffect(() => {
    queueMicrotask(() => setNow(Date.now()));
    void fetchLossReasons().then((reasons) => {
      if (reasons.length) setLossReasons(reasons);
    });
  }, []);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));
  // Стабильный id для DndContext: dnd-kit иначе сидит aria-describedby модульным
  // счётчиком, который расходится между SSR и клиентом → ошибка гидрации. useId
  // даёт одинаковое значение на сервере и при гидрации.
  const dndId = useId();

  function handleDragStart(e: DragStartEvent) {
    const id = String(e.active.id);
    setActiveDeal(stages.flatMap((s) => s.deals).find((d) => d.id === id) ?? null);
  }

  function findDeal(id: string): { deal: Deal; stageId: string } | null {
    for (const s of stages) {
      const deal = s.deals.find((d) => d.id === id);
      if (deal) return { deal, stageId: s.id };
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

    setStages((prev) => moveDealToStage(prev, dealId, targetStage));

    void updateDealStage(dealId, targetStage);
  }

  async function handleCreate(input: DealInput): Promise<boolean> {
    const created = await createDeal(input);
    if (!created) return false;
    setStages((prev) =>
      recomputeStages(prev.map((s) => (s.id === input.stage ? { ...s, deals: [...s.deals, created] } : s))),
    );
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

  function openModal(stageId: string) {
    setModalStage(stageId);
    setModalOpen(true);
  }

  // Поиск (номер/контрагент/описание) + фильтр по приоритету + «только висяки» (SALES-43)
  const q = query.trim().toLowerCase();
  const filteredStages = stages.map((s) => {
    let deals = s.deals;
    if (q) {
      deals = deals.filter((d) =>
        `${d.number} ${d.company} ${d.description ?? ""}`.toLowerCase().includes(q),
      );
    }
    if (priority) deals = deals.filter((d) => d.priority === priority);
    if (stuckOnly) deals = deals.filter((d) => now != null && isStuck(d, s.id, now));
    return { ...s, deals, count: deals.length, sum: deals.reduce((a, d) => a + d.amount, 0) };
  });

  const reasonByCode = new Map(lossReasons.map((r) => [r.code, r.title]));

  /** Вычислить бейджи/плашки Сделки 2.0 для карточки по её стадии и текущему времени. */
  function cardExtras(deal: Deal, stageId: string): CardExtras {
    const code = deal.lostReasonCode;
    return {
      days: now != null ? daysInStage(deal.stageChangedAt, now) : null,
      stuck: now != null && isStuck(deal, stageId, now),
      probability: probabilityFor(deal, stageId),
      weighted: weightedAmount(deal, stageId),
      lostReasonTitle: code ? (reasonByCode.get(code) ?? code) : undefined,
      wonResult: stageId === "won",
      onLose: stageId === "won" || stageId === "lost" ? undefined : () => openLose(deal.id),
    };
  }
  const flatDeals = filteredStages.flatMap((s) =>
    s.deals.map((d) => ({ deal: d, stageTitle: s.title })),
  );
  const PRIORITIES = ["Высокий", "Средний", "Низкий"];

  return (
    <>
      <main className="flex-1 overflow-auto p-6">
        {/* Тулбар */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative min-w-[220px] max-w-sm flex-1">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Поиск сделок..."
              className="w-full rounded-lg border border-line bg-surface py-2 pl-9 pr-3 text-sm text-ink outline-none placeholder:text-faint focus:border-accent"
            />
          </div>
          <button
            onClick={() => setFilterOpen((v) => !v)}
            className={clsx(
              "inline-flex items-center gap-2 rounded-lg border bg-surface px-3.5 py-2 text-sm font-medium hover:bg-sunken",
              priority || filterOpen
                ? "border-accent text-accent-ink"
                : "border-line text-muted",
            )}
          >
            <SlidersHorizontal size={16} /> Фильтры
            {priority && <span className="rounded bg-accent-soft px-1.5 text-xs text-accent-ink">{priority}</span>}
          </button>
          <button
            onClick={() => setStuckOnly((v) => !v)}
            className={clsx(
              "inline-flex items-center gap-2 rounded-lg border bg-surface px-3.5 py-2 text-sm font-medium hover:bg-sunken",
              stuckOnly ? "border-amber-400 text-amber-700" : "border-line text-muted",
            )}
          >
            <Clock size={16} /> Только висяки
          </button>
          <button
            onClick={() => openModal(stages[0]?.id ?? "new")}
            className="ml-auto inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-accent-ink"
          >
            <Plus size={16} /> Создать сделку
          </button>
        </div>

        {/* Фильтр по приоритету */}
        {filterOpen && (
          <div className="mt-3 flex items-center gap-2">
            <span className="text-sm text-muted">Приоритет:</span>
            {[null, ...PRIORITIES].map((p) => (
              <button
                key={p ?? "all"}
                onClick={() => setPriority(p)}
                className={clsx(
                  "rounded-lg px-3 py-1 text-sm font-medium",
                  priority === p
                    ? "bg-accent-soft text-accent-ink"
                    : "bg-surface text-muted ring-1 ring-line hover:bg-sunken",
                )}
              >
                {p ?? "Все"}
              </button>
            ))}
          </div>
        )}

        {/* План / Факт по периодам */}
        <section className="mt-5">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <h2 className="font-semibold text-ink">План / Факт</h2>
              <span className="hidden items-center gap-1.5 text-[11px] text-muted sm:flex">
                <span className="text-emerald-500">●</span>≥100%
                <span className="text-amber-500">●</span>70–99%
                <span className="text-red-500">●</span>&lt;70%
              </span>
            </div>
            <div className="flex items-center gap-0.5 rounded-lg border border-line bg-surface p-0.5">
              {PERIODS.map((p) => (
                <button
                  key={p.key}
                  onClick={() => handlePeriod(p.key)}
                  className={clsx(
                    "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                    period === p.key
                      ? "bg-accent-soft text-accent-ink"
                      : "text-muted hover:text-ink",
                  )}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
            {kpis.map((kpi) => (
              <KpiCard key={kpi.id} kpi={kpi} onLog={() => handleLog(kpi.id)} />
            ))}
          </div>
        </section>

        {/* Переключатель вида */}
        <div className="mt-5 flex items-center justify-end gap-2">
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

        {view === "board" ? (
          /* Канбан с drag&drop */
          <DndContext id={dndId} sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
            <div className="mt-3 flex gap-4 overflow-x-auto pb-2 thin-scroll">
              {filteredStages.map((stage) => (
                <Column key={stage.id} stage={stage} onAdd={() => openModal(stage.id)}>
                  {stage.deals.map((deal) => (
                    <DraggableDeal
                      key={deal.id}
                      deal={deal}
                      extras={cardExtras(deal, stage.id)}
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
                  <DealCard deal={activeDeal} />
                </div>
              ) : null}
            </DragOverlay>
          </DndContext>
        ) : (
          /* Список */
          <div className="mt-3 overflow-hidden rounded-xl bg-surface shadow-card">
            <table className="w-full text-sm">
              <thead className="border-b border-line text-left text-xs text-muted">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Номер</th>
                  <th className="px-4 py-2.5 font-medium">Контрагент</th>
                  <th className="px-4 py-2.5 font-medium">Описание</th>
                  <th className="px-4 py-2.5 font-medium">Стадия</th>
                  <th className="px-4 py-2.5 text-right font-medium">Сумма</th>
                </tr>
              </thead>
              <tbody>
                {flatDeals.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-6 text-center text-muted">
                      Сделок не найдено
                    </td>
                  </tr>
                )}
                {flatDeals.map(({ deal, stageTitle }) => (
                  <tr key={deal.id} className="border-b border-line last:border-0 hover:bg-sunken">
                    <td className="px-4 py-2.5">
                      <Link href={`/crm/deals/${deal.id}`} className="font-medium text-accent-ink">
                        {deal.number}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-ink">{deal.company}</td>
                    <td className="px-4 py-2.5 text-muted">{deal.description}</td>
                    <td className="px-4 py-2.5 text-muted">{stageTitle}</td>
                    <td className="px-4 py-2.5 text-right font-medium text-ink">
                      {formatMoney(deal.amount)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <FunnelTotals data={computeFunnel(filteredStages)} />
      </main>

      <ChatsPanel />

      {modalOpen && (
        <CreateDealModal
          stages={stages}
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
          setStages((prev) => moveDealToStage(prev, dealId, stageId));
          // Поддерживаем превью консистентным: если перенесли активный deal, обновляем ссылку
          setPreviewDeal((p) =>
            p && p.id === dealId
              ? (stages.flatMap((s) => s.deals).find((d) => d.id === dealId) ?? p)
              : p,
          );
          void updateDealStage(dealId, stageId);
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
