"use client";

import { useCallback, useState } from "react";

import {
  type AnalyticsData,
  fetchAnalytics,
  fmtByn,
  fmtNh,
  fmtPct,
  kpiTone,
} from "@/lib/production-analytics";

const MONTHS = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"];

interface Props {
  initial: AnalyticsData | null;
}

export function ProductionAnalyticsView({ initial }: Props) {
  const [data, setData] = useState<AnalyticsData | null>(initial);
  const [year, setYear] = useState(new Date().getFullYear());
  const [loading, setLoading] = useState(false);

  const loadYear = useCallback(async (y: number) => {
    setLoading(true);
    const d = await fetchAnalytics(y);
    setData(d);
    setYear(y);
    setLoading(false);
  }, []);

  if (!data) {
    return (
      <div className="p-6 text-gray-500 text-sm">
        Данные аналитики недоступны. Проверьте соединение с сервером.
      </div>
    );
  }

  const maxNh = Math.max(...data.plan_fact_by_month.map((m) => Math.max(m.plan_nh, m.fact_nh)), 1);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => loadYear(year - 1)}
          className="px-3 py-1 text-sm border rounded hover:bg-gray-50"
        >
          ‹
        </button>
        <span className="font-semibold text-lg">{year}</span>
        <button
          onClick={() => loadYear(year + 1)}
          className="px-3 py-1 text-sm border rounded hover:bg-gray-50"
        >
          ›
        </button>
        {loading && <span className="text-xs text-gray-400 ml-2">Загрузка…</span>}
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        <KpiCard
          label="Выработка факт"
          value={`${fmtNh(data.vyrabotka_fact_nh)} н.ч`}
          sub={`план: ${fmtNh(data.vyrabotka_plan_nh)} н.ч`}
          color="text-gray-800"
        />
        <KpiCard
          label="Эффективность"
          value={fmtPct(data.efficiency_pct)}
          color={kpiTone("high", data.efficiency_pct)}
        />
        <KpiCard
          label="FPY (с 1 предъявл.)"
          value={fmtPct(data.fpy_pct)}
          color={kpiTone("high", data.fpy_pct)}
        />
        <KpiCard
          label="Пропускаемость"
          value={fmtPct(data.pass_rate_pct)}
          color={kpiTone("high", data.pass_rate_pct)}
        />
        <KpiCard
          label="Брак"
          value={fmtPct(data.scrap_pct)}
          color={kpiTone("low", data.scrap_pct)}
        />
        <KpiCard
          label="Премия ФОТ"
          value={fmtByn(data.premium_fot_byn)}
          color="text-gray-800"
        />
      </div>

      {/* Plan / Fact chart */}
      <div>
        <h3 className="text-sm font-medium text-gray-700 mb-3">План / Факт н.ч по месяцам</h3>
        <div className="flex items-end gap-2 h-32 border-b border-gray-200 pb-1">
          {data.plan_fact_by_month.map((m, i) => {
            const planH = Math.round((m.plan_nh / maxNh) * 100);
            const factH = Math.round((m.fact_nh / maxNh) * 100);
            return (
              <div key={m.month} className="flex-1 flex flex-col items-center gap-0.5">
                <div className="w-full flex items-end gap-0.5 h-24">
                  <div
                    className="flex-1 rounded-t bg-blue-300 opacity-80"
                    style={{ height: `${planH}%`, minHeight: planH > 0 ? "2px" : "0" }}
                    title={`план: ${fmtNh(m.plan_nh)} н.ч`}
                  />
                  <div
                    className="flex-1 rounded-t bg-green-400 opacity-70"
                    style={{ height: `${factH}%`, minHeight: factH > 0 ? "2px" : "0" }}
                    title={`факт: ${fmtNh(m.fact_nh)} н.ч`}
                  />
                </div>
                <span className="text-xs text-gray-400">{MONTHS[i]}</span>
              </div>
            );
          })}
        </div>
        <div className="flex gap-4 mt-1 text-xs text-gray-500">
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-3 bg-blue-300 rounded-sm" /> план
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-3 bg-green-400 rounded-sm" /> факт
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Scrap reasons */}
        <div>
          <h3 className="text-sm font-medium text-gray-700 mb-2">Причины брака</h3>
          {data.scrap_reasons.length === 0 ? (
            <p className="text-xs text-gray-400">Нет данных</p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-1 text-gray-500 font-medium">Причина</th>
                  <th className="text-right py-1 text-gray-500 font-medium">Кол-во</th>
                  <th className="text-right py-1 text-gray-500 font-medium">Доля</th>
                </tr>
              </thead>
              <tbody>
                {data.scrap_reasons.map((r) => {
                  const total = data.scrap_reasons.reduce((s, x) => s + x.count, 0);
                  const pct = total > 0 ? (r.count / total) * 100 : 0;
                  return (
                    <tr key={r.reason} className="border-b border-gray-100">
                      <td className="py-1 text-gray-700 truncate max-w-[120px]">{r.reason}</td>
                      <td className="py-1 text-right text-gray-600">{r.count}</td>
                      <td className="py-1 text-right text-gray-500">{pct.toFixed(0)}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Team contribution */}
        <div>
          <h3 className="text-sm font-medium text-gray-700 mb-2">Вклад сборщиков</h3>
          {data.team_contribution.length === 0 ? (
            <p className="text-xs text-gray-400">Нет данных</p>
          ) : (
            <div className="space-y-1.5">
              {data.team_contribution.map((member) => (
                <div key={member.name} className="flex items-center gap-2">
                  <span className="text-xs text-gray-600 w-24 truncate">{member.name}</span>
                  <div className="flex-1 bg-gray-100 rounded-full h-2">
                    <div
                      className="bg-blue-400 h-2 rounded-full"
                      style={{ width: `${Math.min(100, member.share_pct)}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-500 w-10 text-right">
                    {member.share_pct.toFixed(0)}%
                  </span>
                  <span className="text-xs text-gray-400 w-16 text-right">
                    {fmtNh(member.nh_output)} н.ч
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Top products */}
        <div>
          <h3 className="text-sm font-medium text-gray-700 mb-2">Топ изделий (факт н.ч)</h3>
          {data.top_products.length === 0 ? (
            <p className="text-xs text-gray-400">Нет данных</p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-1 text-gray-500 font-medium">Изделие</th>
                  <th className="text-right py-1 text-gray-500 font-medium">Факт н.ч</th>
                </tr>
              </thead>
              <tbody>
                {data.top_products.slice(0, 5).map((p) => (
                  <tr key={p.product} className="border-b border-gray-100">
                    <td className="py-1 text-gray-700 truncate max-w-[140px]">{p.product}</td>
                    <td className="py-1 text-right text-gray-600 font-medium">
                      {fmtNh(p.fact_nh)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

function KpiCard({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: string;
  sub?: string;
  color: string;
}) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg px-4 py-3">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className={`text-lg font-semibold ${color}`}>{value}</div>
      {sub && <div className="text-xs text-gray-400 mt-0.5">{sub}</div>}
    </div>
  );
}
