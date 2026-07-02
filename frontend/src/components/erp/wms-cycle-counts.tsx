"use client";

import clsx from "clsx";
import { Plus, Play } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  createCyclePlan,
  type CyclePlan,
  dueState,
  fetchCyclePlans,
  runCyclePlan,
} from "@/lib/wms-warehouse";

const DUE_STYLES: Record<string, string> = {
  overdue: "bg-red-50 text-red-600",
  today: "bg-amber-50 text-amber-600",
  upcoming: "bg-sunken text-muted",
  none: "bg-sunken text-faint",
};
const DUE_LABELS: Record<string, string> = {
  overdue: "Просрочено",
  today: "Сегодня",
  upcoming: "Предстоит",
  none: "—",
};

export function WmsCycleCounts({ initial, today }: { initial: CyclePlan[]; today: string }) {
  const router = useRouter();
  const [plans, setPlans] = useState<CyclePlan[]>(initial);
  const [form, setForm] = useState({ warehouse: "Главный", zone: "", cadence_days: "30" });
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setPlans(await fetchCyclePlans());
  }
  async function onAdd() {
    if (!form.warehouse.trim()) return;
    setBusy(true);
    await createCyclePlan({
      warehouse: form.warehouse.trim(),
      zone: form.zone.trim() || null,
      cadence_days: Number(form.cadence_days) || 30,
      next_due_date: today,
    });
    await refresh();
    setBusy(false);
  }
  async function onRun(id: number) {
    setBusy(true);
    const doc = await runCyclePlan(id);
    setBusy(false);
    if (doc) router.push(`/erp/wms/inventory/${doc.id}`);
    else await refresh();
  }

  return (
    <div className="flex-1 overflow-auto p-6">
      <p className="text-sm text-muted">
        Расписание циклического пересчёта. Запуск создаёт документ инвентаризации, заполненный
        ожидаемым из 1С, и сдвигает срок на период плана.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <input value={form.warehouse} onChange={(e) => setForm({ ...form, warehouse: e.target.value })}
          placeholder="Склад" className="rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent" />
        <input value={form.zone} onChange={(e) => setForm({ ...form, zone: e.target.value })}
          placeholder="Зона (опц.)" className="rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent" />
        <input value={form.cadence_days} onChange={(e) => setForm({ ...form, cadence_days: e.target.value })}
          inputMode="numeric" placeholder="Период, дн" className="w-28 rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent" />
        <button onClick={onAdd} disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60">
          <Plus size={16} /> План
        </button>
      </div>

      <div className="mt-4 overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Склад</th>
              <th className="px-4 py-2 font-medium">Зона</th>
              <th className="px-4 py-2 text-right font-medium">Период</th>
              <th className="px-4 py-2 font-medium">Следующий</th>
              <th className="px-4 py-2 font-medium">Статус</th>
              <th className="px-4 py-2 text-right font-medium" />
            </tr>
          </thead>
          <tbody>
            {plans.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-6 text-center text-muted">Планов пока нет</td></tr>
            )}
            {plans.map((p) => {
              const st = dueState(p.next_due_date, today);
              return (
                <tr key={p.id} className="border-b border-line last:border-0">
                  <td className="px-4 py-2.5 text-ink">{p.warehouse}</td>
                  <td className="px-4 py-2.5 text-muted">{p.zone || "весь склад"}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-muted">{p.cadence_days} дн</td>
                  <td className="px-4 py-2.5 text-muted">{p.next_due_date || "—"}</td>
                  <td className="px-4 py-2.5">
                    <span className={clsx("inline-flex rounded-md px-2 py-0.5 text-xs font-medium", DUE_STYLES[st])}>
                      {DUE_LABELS[st]}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <button onClick={() => onRun(p.id)} disabled={busy}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-line px-2 py-1 text-xs text-muted hover:bg-sunken disabled:opacity-60">
                      <Play size={13} /> Запустить
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
