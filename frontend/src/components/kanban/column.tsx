import { Plus } from "lucide-react";
import { DealCard } from "@/components/kanban/deal-card";
import { formatMoney } from "@/lib/format";
import type { Stage } from "@/lib/types";

function pluralDeals(n: number): string {
  const d10 = n % 10;
  const d100 = n % 100;
  if (d10 === 1 && d100 !== 11) return "сделка";
  if (d10 >= 2 && d10 <= 4 && (d100 < 12 || d100 > 14)) return "сделки";
  return "сделок";
}

export function Column({ stage }: { stage: Stage }) {
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

      <div className="flex flex-col gap-3">
        {stage.deals.map((deal) => (
          <DealCard key={deal.id} deal={deal} />
        ))}
        <button className="flex items-center justify-center gap-1.5 rounded-xl border border-dashed border-slate-300 py-2.5 text-xs font-medium text-slate-500 hover:bg-white">
          <Plus size={14} /> Добавить сделку
        </button>
      </div>
    </div>
  );
}
