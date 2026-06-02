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
import {
  ChevronDown,
  LayoutGrid,
  List,
  MoreHorizontal,
  Plus,
  Search,
  Settings2,
  SlidersHorizontal,
} from "lucide-react";
import { useState } from "react";
import { ChatsPanel } from "@/components/chats-panel";
import { FunnelTotals } from "@/components/funnel-totals";
import { CreateDealModal } from "@/components/kanban/create-deal-modal";
import { DealCard } from "@/components/kanban/deal-card";
import { KpiCard } from "@/components/kpi-card";
import { createDeal, updateDealStage, type DealInput } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import { KPIS } from "@/lib/mock-data";
import type { Deal, Stage } from "@/lib/types";

function pluralDeals(n: number): string {
  const d10 = n % 10;
  const d100 = n % 100;
  if (d10 === 1 && d100 !== 11) return "сделка";
  if (d10 >= 2 && d10 <= 4 && (d100 < 12 || d100 > 14)) return "сделки";
  return "сделок";
}

function recompute(stages: Stage[]): Stage[] {
  return stages.map((s) => ({
    ...s,
    count: s.deals.length,
    sum: s.deals.reduce((acc, d) => acc + d.amount, 0),
  }));
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

export function DealsWorkspace({ initialStages }: { initialStages: Stage[] }) {
  const [stages, setStages] = useState<Stage[]>(initialStages);
  const [activeDeal, setActiveDeal] = useState<Deal | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalStage, setModalStage] = useState<string>(initialStages[0]?.id ?? "new");

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

    setStages((prev) => {
      const source = prev.find((s) => s.deals.some((d) => d.id === dealId));
      if (!source || source.id === targetStage) return prev;
      const deal = source.deals.find((d) => d.id === dealId);
      if (!deal) return prev;
      const next = prev.map((s) => {
        if (s.id === source.id) return { ...s, deals: s.deals.filter((d) => d.id !== dealId) };
        if (s.id === targetStage) return { ...s, deals: [...s.deals, deal] };
        return s;
      });
      return recompute(next);
    });

    void updateDealStage(dealId, targetStage);
  }

  async function handleCreate(input: DealInput): Promise<boolean> {
    const created = await createDeal(input);
    if (!created) return false;
    setStages((prev) =>
      recompute(prev.map((s) => (s.id === input.stage ? { ...s, deals: [...s.deals, created] } : s))),
    );
    setModalOpen(false);
    return true;
  }

  function openModal(stageId: string) {
    setModalStage(stageId);
    setModalOpen(true);
  }

  return (
    <>
      <main className="flex-1 overflow-auto p-6">
        {/* Тулбар */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative min-w-[220px] max-w-sm flex-1">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              placeholder="Поиск сделок..."
              className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-9 pr-3 text-sm outline-none placeholder:text-slate-400 focus:border-brand"
            />
          </div>
          <button className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50">
            <SlidersHorizontal size={16} /> Фильтры
          </button>
          <button className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50">
            <Settings2 size={16} /> Настроить воронку
          </button>
          <button
            onClick={() => openModal(stages[0]?.id ?? "new")}
            className="ml-auto inline-flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-brand-700"
          >
            <Plus size={16} /> Создать сделку <ChevronDown size={16} />
          </button>
        </div>

        {/* План на сегодня */}
        <section className="mt-5">
          <h2 className="mb-3 font-semibold text-ink">План на сегодня</h2>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
            {KPIS.map((kpi) => (
              <KpiCard key={kpi.id} kpi={kpi} />
            ))}
          </div>
        </section>

        {/* Переключатель вида */}
        <div className="mt-5 flex items-center justify-end gap-2">
          <div className="flex items-center gap-0.5 rounded-lg border border-slate-200 bg-white p-0.5">
            <button className="rounded-md bg-brand-100 p-1.5 text-brand-600">
              <LayoutGrid size={16} />
            </button>
            <button className="rounded-md p-1.5 text-slate-400">
              <List size={16} />
            </button>
          </div>
          <button className="rounded-lg border border-slate-200 bg-white p-2 text-slate-400">
            <MoreHorizontal size={16} />
          </button>
        </div>

        {/* Канбан с drag&drop */}
        <DndContext sensors={sensors} onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
          <div className="mt-3 flex gap-4 overflow-x-auto pb-2 thin-scroll">
            {stages.map((stage) => (
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

        <FunnelTotals />
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
