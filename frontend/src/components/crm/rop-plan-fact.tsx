"use client";

import { useCallback, useEffect, useState } from "react";

interface ManagerRow {
  name: string;
  plan_deals: number;
  fact_deals: number;
  plan_revenue: number;
  fact_revenue: number;
  conversion_pct: number;
}

interface PlanFactData {
  period: string;
  managers: ManagerRow[];
  demo_plans: boolean;
}

function pct(fact: number, plan: number): number {
  if (plan <= 0) return 0;
  return Math.round((fact / plan) * 100);
}

function PctBadge({ value }: { value: number }) {
  const cls =
    value >= 100
      ? "bg-emerald-50 text-emerald-700"
      : value >= 70
        ? "bg-amber-50 text-amber-700"
        : "bg-red-50 text-red-600";
  return (
    <span className={`inline-block rounded-md px-2 py-0.5 text-xs font-semibold ${cls}`}>
      {value}%
    </span>
  );
}

function fmt(n: number): string {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(n);
}

export function RopPlanFact({ defaultPeriod }: { defaultPeriod: string }) {
  const [period, setPeriod] = useState(defaultPeriod);
  const [data, setData] = useState<PlanFactData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (p: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/sales/rop/plan-fact?period=${p}`, {
        cache: "no-store",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(period);
  }, [period, load]);

  return (
    <div className="space-y-4">
      {/* Фильтр периода */}
      <div className="flex items-center gap-3">
        <label className="text-sm text-muted">Период:</label>
        <input
          type="month"
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
          className="rounded-lg border border-line bg-canvas px-3 py-1.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-accent"
        />
        {data?.demo_plans && (
          <span className="rounded-md bg-amber-50 px-2 py-0.5 text-xs text-amber-700">
            демо-план
          </span>
        )}
      </div>

      {/* Состояния */}
      {loading && <p className="text-sm text-muted">Загрузка…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {/* Таблица */}
      {!loading && !error && data && (
        data.managers.length === 0 ? (
          <p className="text-sm text-muted">Нет данных за этот период.</p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-line">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-line bg-sunken text-[10px] uppercase tracking-wide text-faint">
                  <th className="px-4 py-2.5 text-left font-semibold">Менеджер</th>
                  <th className="px-4 py-2.5 text-right font-semibold">План сделок</th>
                  <th className="px-4 py-2.5 text-right font-semibold">Факт</th>
                  <th className="px-4 py-2.5 text-center font-semibold">% выполнения</th>
                  <th className="px-4 py-2.5 text-right font-semibold">План выручки</th>
                  <th className="px-4 py-2.5 text-right font-semibold">Факт выручки</th>
                  <th className="px-4 py-2.5 text-center font-semibold">% выручки</th>
                  <th className="px-4 py-2.5 text-right font-semibold">Конверсия</th>
                </tr>
              </thead>
              <tbody>
                {data.managers.map((m) => {
                  const dealsPct = pct(m.fact_deals, m.plan_deals);
                  const revPct = pct(m.fact_revenue, m.plan_revenue);
                  return (
                    <tr key={m.name} className="border-b border-line last:border-0">
                      <td className="px-4 py-3 font-medium text-ink">{m.name}</td>
                      <td className="px-4 py-3 text-right tabular-nums text-muted">
                        {m.plan_deals}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums font-semibold text-ink">
                        {m.fact_deals}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <PctBadge value={dealsPct} />
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-muted">
                        {fmt(m.plan_revenue)} BYN
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums font-semibold text-ink">
                        {fmt(m.fact_revenue)} BYN
                      </td>
                      <td className="px-4 py-3 text-center">
                        <PctBadge value={revPct} />
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-muted">
                        {m.conversion_pct}%
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )
      )}
    </div>
  );
}
