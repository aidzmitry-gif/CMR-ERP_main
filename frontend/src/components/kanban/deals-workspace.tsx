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
import { LayoutGrid, List, Plus, Search, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { ChatsPanel } from "@/components/chats-panel";
import { FunnelTotals } from "@/components/funnel-totals";
import { CreateDealModal } from "@/components/kanban/create-deal-modal";
import { DealCard } from "@/components/kanban/deal-card";
import { KpiCard } from "@/components/kpi-card";
import { createDeal, getKpis, logActivity, updateDealStage, type DealInput } from "@/lib/api";
import { moveDealToStage, recomputeStages } from "@/lib/board";
import { formatMoney } from "@/lib/format";
import { computeFunnel } from "@/lib/funnel";
import type { Deal, Kpi, Stage } from "@/lib/types";

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

function DraggableDeal({ deal }: { deal: Deal }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: deal.id });
  return (
    <div ref={setNodeRef} {...attributes} {...listeners} className={isDragging ? "opacity-40" : ""}>
      <DealCard deal={deal} />
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
  return (
    <div className="flex w-[300px] shrink-0 flex-col gap-3">
      <div className="overflow-hidden rounded-xl bg-white shadow-card">
        <div className="h-1" style={{ backgroundColor: stage.color }} />
        <div className="px-4 py-3">
          <div className="font-semibold text-ink">{stage.title}</div>
          <div className="mt-0.5 text-xs text-muted">
            {stage.count} {pluralDeals(stage.count)} · {formatMoney(stage.sum)}
          </div>
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

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));

  function handleDragStart(e: DragStartEvent) {
    const id = String(e.active.id);
    setActiveDeal(stages.flatMap((s) => s.deals).find((d) => d.id === id) ?? null);
  }

  function handleDragEnd(e: DragEndEvent) {
    setActiveDeal(null);
    const dealId = String(e.active.id);
    const targetStage = e.over ? String(e.over.id) : null;
    if (!targetStage) return;

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

  // Поиск (номер/контрагент/описание) + фильтр по приоритету
  const q = query.trim().toLowerCase();
  const filteredStages = stages.map((s) => {
    let deals = s.deals;
    if (q) {
      deals = deals.filter((d) =>
        `${d.number} ${d.company} ${d.description ?? ""}`.toLowerCase().includes(q),
      );
    }
    if (priority) deals = deals.filter((d) => d.priority === priority);
    return { ...s, deals, count: deals.length, sum: deals.reduce((a, d) => a + d.amount, 0) };
  });
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
          <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
            <div className="mt-3 flex gap-4 overflow-x-auto pb-2 thin-scroll">
              {filteredStages.map((stage) => (
                <Column key={stage.id} stage={stage} onAdd={() => openModal(stage.id)}>
                  {stage.deals.map((deal) => (
                    <DraggableDeal key={deal.id} deal={deal} />
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
    </>
  );
}
