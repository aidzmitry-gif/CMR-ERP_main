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
import { AppShell } from "@/components/app-shell";
import { ChatsPanel } from "@/components/chats-panel";
import { FunnelTotals } from "@/components/funnel-totals";
import { Board } from "@/components/kanban/board";
import { KpiCard } from "@/components/kpi-card";
import { KPIS } from "@/lib/mock-data";

export default function DealsPage() {
  return (
    <AppShell crumbs={["CRM", "Сделки"]}>
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
          <button className="ml-auto inline-flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-brand-700">
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

        {/* Канбан */}
        <div className="mt-3">
          <Board />
        </div>

        {/* Итоги по воронке */}
        <FunnelTotals />
      </main>

      <ChatsPanel />
    </AppShell>
  );
}
