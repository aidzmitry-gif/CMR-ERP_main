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
import { useEffect, useId, useState } from "react";
import { ChatsPanel } from "@/components/chats-panel";
import { FunnelTotals } from "@/components/funnel-totals";
import { CreateDealModal } from "@/components/kanban/create-deal-modal";
import { DealCard } from "@/components/kanban/deal-card";
import { LoseDealModal } from "@/components/kanban/lose-deal-modal";
import { KpiCard } from "@/components/kpi-card";
import {
  createDeal,
  fetchLossReasons,
  getKpis,
  logActivity,
  loseDeal,
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

function DraggableDeal({ deal, extras }: { deal: Deal; extras: CardExtras }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: deal.id });
  return (
    <div ref={setNodeRef} {...attributes} {...listeners} className={isDragging ? "opacity-40" : ""}>
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
      <div className="overflow-hidden rounded-xl bg-white shadow-card">
        <div className="h-1" style={{ backgroundColor: stage.color }} />
        <div className="px-4 py-3">
          <div className="font-semibold text-ink">{stage.title}</div>
          <div className="mt-0.5 text-xs text-muted">
            {stage.count} {pluralDeals(stage.count)} · {formatMoney(stage.sum)}
          </div>
          {showWeighted && (
            <div className="mt-0.5 text-[11px] font-semibold text-brand-700">
              взвешенно: {formatMoney(stageWeightedSum(stage))}
            </div>
          )}
        </div>
      </div>
      <div
        ref={setNodeRef}
        className={clsx(
          "flex min-h-20 flex-col gap-3 rounded-xl p-1 transition-colors",
          isOver && "bg-brand-100/60 ring-2 ring-brand-100",
        )}
      >
        {children}
        <button
          onClick={onAdd}
          className="flex items-center justify-center gap-1.5 rounded-xl border border-dashed border-slate-300 py-2.5 text-xs font-medium text-slate-500 hover:bg-white"
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
  const [stages, setStages] = useState<Stage[]>(initialStages);
  const [kpis, setKpis] = useState<Kpi[]>(initialKpis);
  const [period, setPeriod] = useState("day");
  const [activeDeal, setActiveDeal] = useState<Deal | null>(null);
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
    setNow(Date.now());
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
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Поиск сделок..."
              className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-9 pr-3 text-sm outline-none placeholder:text-slate-400 focus:border-brand"
            />
          </div>
          <button
            onClick={() => setFilterOpen((v) => !v)}
            className={clsx(
              "inline-flex items-center gap-2 rounded-lg border bg-white px-3.5 py-2 text-sm font-medium hover:bg-slate-50",
              priority || filterOpen
                ? "border-brand text-brand-600"
                : "border-slate-200 text-slate-600",
            )}
          >
            <SlidersHorizontal size={16} /> Фильтры
            {priority && <span className="rounded bg-brand-100 px-1.5 text-xs">{priority}</span>}
          </button>
          <button
            onClick={() => setStuckOnly((v) => !v)}
            className={clsx(
              "inline-flex items-center gap-2 rounded-lg border bg-white px-3.5 py-2 text-sm font-medium hover:bg-slate-50",
              stuckOnly ? "border-amber-400 text-amber-700" : "border-slate-200 text-slate-600",
            )}
          >
            <Clock size={16} /> Только висяки
          </button>
          <button
            onClick={() => openModal(stages[0]?.id ?? "new")}
            className="ml-auto inline-flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-brand-700"
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
                    ? "bg-brand-100 text-brand-600"
                    : "bg-white text-slate-500 ring-1 ring-slate-200 hover:bg-slate-50",
                )}
              >
                {p ?? "Все"}
              </button>
            ))}
          </div>
        )}

        {/* План / Факт по периодам */}
        <section className="mt-5">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold text-ink">План / Факт</h2>
            <div className="flex items-center gap-0.5 rounded-lg border border-slate-200 bg-white p-0.5">
              {PERIODS.map((p) => (
                <button
                  key={p.key}
                  onClick={() => handlePeriod(p.key)}
                  className={clsx(
                    "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                    period === p.key
                      ? "bg-brand-100 text-brand-600"
                      : "text-slate-500 hover:text-slate-700",
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
          <div className="flex items-center gap-0.5 rounded-lg border border-slate-200 bg-white p-0.5">
            <button
              onClick={() => setView("board")}
              title="Канбан"
              className={clsx(
                "rounded-md p-1.5",
                view === "board" ? "bg-brand-100 text-brand-600" : "text-slate-400 hover:text-slate-600",
              )}
            >
              <LayoutGrid size={16} />
            </button>
            <button
              onClick={() => setView("list")}
              title="Список"
              className={clsx(
                "rounded-md p-1.5",
                view === "list" ? "bg-brand-100 text-brand-600" : "text-slate-400 hover:text-slate-600",
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
                    <DraggableDeal key={deal.id} deal={deal} extras={cardExtras(deal, stage.id)} />
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
          <div className="mt-3 overflow-hidden rounded-xl bg-white shadow-card">
            <table className="w-full text-sm">
              <thead className="border-b border-slate-100 text-left text-xs text-muted">
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
                  <tr key={deal.id} className="border-b border-slate-50 last:border-0 hover:bg-slate-50">
                    <td className="px-4 py-2.5">
                      <Link href={`/crm/deals/${deal.id}`} className="font-medium text-brand-600">
                        {deal.number}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-ink">{deal.company}</td>
                    <td className="px-4 py-2.5 text-slate-600">{deal.description}</td>
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
    </>
  );
}
