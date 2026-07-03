"use client";

import clsx from "clsx";
import { useCallback, useEffect, useState } from "react";
import { fetchFunnels, type FunnelRow } from "@/lib/api";
import { formatByn } from "@/lib/format";

/**
 * Аналитика воронки (П7 ТЗ): воронкообразная визуализация стадий с count/sum/weighted,
 * полоски конверсии стадия→стадия, плитки взвеш.прогноз/средний цикл won/висяки.
 * Источник — `/sales/pipeline/analytics?funnel=&owner=`. Без графических библиотек:
 * полоса колонки = доля count от max; полоска конверсии — % шириной. Все состояния.
 *
 * «Висяки» — из существующего отчёта `?stuck_days=N` (бэк уже умеет, переиспользуем).
 */
type StageAnalytics = {
  id: string;
  title: string;
  color: string;
  count: number;
  sum: number;
  weighted: number;
  avg_age_days: number | null;
  next_conv_pct: number | null;
};

type Analytics = {
  funnel: string;
  stages: StageAnalytics[];
  forecast_weighted: number;
  avg_cycle_days: number | null;
  won_count: number;
};

// S3-6: взвешенный прогноз валовой маржи воронки (`/sales/pipeline/margin-forecast`).
type MarginForecast = {
  funnel: string;
  owner: string | null;
  revenue_weighted: number;
  gross_weighted: number | null;
  margin_pct_blended: number | null;
  deals_priced: number;
  deals_total: number;
  reason: string | null;
};

type Status = "loading" | "error" | "ready";

// Период-срез конверсии/времени на стадии (`/sales/pipeline/stage-metrics`) — отдельный
// от снимка доски выше: считается по истории DealStageEvent за окно [date_from, date_to].
type StageMetric = {
  id: string;
  title: string;
  color: string;
  entered_count: number;
  conv_next_pct: number | null;
  avg_time_days: number | null;
  completed_count: number;
};

type StageMetrics = {
  funnel: string;
  date_from: string;
  date_to: string;
  stages: StageMetric[];
};

const METRIC_PERIODS = [
  { key: "week", label: "Неделя" },
  { key: "month", label: "Месяц" },
  { key: "quarter", label: "Квартал" },
] as const;
type MetricPeriod = (typeof METRIC_PERIODS)[number]["key"] | "range";

export function PipelineAnalytics({ initialFunnel = "new_clients" }: { initialFunnel?: string }) {
  const [funnels, setFunnels] = useState<FunnelRow[]>([]);
  const [funnel, setFunnel] = useState(initialFunnel);
  const [owner, setOwner] = useState("");
  // Продавцы для фильтра — реальные значения Deal.owner (не выдуманный справочник):
  // тянем плоский список сделок один раз и берём непустые уникальные имена.
  const [owners, setOwners] = useState<string[]>([]);
  const [status, setStatus] = useState<Status>("loading");
  const [data, setData] = useState<Analytics | null>(null);
  const [margin, setMargin] = useState<MarginForecast | null>(null);
  const [stuck, setStuck] = useState<number | null>(null);

  // Период-переключатель для графиков конверсии/времени на стадии.
  const [metricPeriod, setMetricPeriod] = useState<MetricPeriod>("month");
  const [rangeFrom, setRangeFrom] = useState("");
  const [rangeTo, setRangeTo] = useState("");
  // Счётчик кликов «Применить» — force-триггер эффекта, когда metricPeriod уже "range"
  // (простое setMetricPeriod("range") тогда не меняет state → React не переисполнит эффект).
  const [rangeApplyToken, setRangeApplyToken] = useState(0);
  const [metricsStatus, setMetricsStatus] = useState<Status>("loading");
  const [metrics, setMetrics] = useState<StageMetrics | null>(null);

  useEffect(() => {
    void fetchFunnels().then(setFunnels);
    void fetch("/api/sales/deals", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: { owner?: string }[]) => {
        const names = Array.from(new Set(rows.map((d) => d.owner).filter(Boolean))) as string[];
        setOwners(names.sort((a, b) => a.localeCompare(b, "ru")));
      })
      .catch(() => setOwners([]));
  }, []);

  const loadMetrics = useCallback(
    async (f: string, o: string, p: MetricPeriod, from: string, to: string) => {
      if (p === "range" && (!from || !to)) return; // диапазон выбран не полностью — ждём
      setMetricsStatus("loading");
      try {
        const qs = new URLSearchParams({ funnel: f });
        if (o) qs.set("owner", o);
        if (p === "range") {
          qs.set("date_from", from);
          qs.set("date_to", to);
        } else {
          qs.set("period", p);
        }
        const res = await fetch(`/api/sales/pipeline/stage-metrics?${qs.toString()}`, {
          cache: "no-store",
        });
        if (!res.ok) throw new Error(String(res.status));
        setMetrics((await res.json()) as StageMetrics);
        setMetricsStatus("ready");
      } catch {
        setMetricsStatus("error");
      }
    },
    [],
  );

  // rangeFrom/rangeTo намеренно не в зависимостях: набор дат в input не должен слать
  // запрос на каждый keystroke — диапазон применяется явно кнопкой «Применить»
  // (rangeApplyToken форсирует повторный фетч, даже если metricPeriod уже был "range").
  useEffect(() => {
    void loadMetrics(funnel, owner, metricPeriod, rangeFrom, rangeTo);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [funnel, owner, metricPeriod, rangeApplyToken, loadMetrics]);

  const load = useCallback(async (f: string, o: string) => {
    setStatus("loading");
    try {
      const qs = new URLSearchParams({ funnel: f });
      if (o) qs.set("owner", o);
      const res = await fetch(`/api/sales/pipeline/analytics?${qs.toString()}`, { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      setData((await res.json()) as Analytics);
      // S3-6: прогноз маржи воронки — отдельный endpoint, тот же фильтр funnel/owner.
      try {
        const mres = await fetch(`/api/sales/pipeline/margin-forecast?${qs.toString()}`, {
          cache: "no-store",
        });
        setMargin(mres.ok ? ((await mres.json()) as MarginForecast) : null);
      } catch {
        setMargin(null);
      }
      // «Висяки» — отдельный отчёт; ?stuck_days=14 канонично.
      try {
        const sres = await fetch(`/api/sales/deals?stuck_days=14`, { cache: "no-store" });
        if (sres.ok) {
          const list = (await sres.json()) as { funnel?: string }[];
          setStuck(list.filter((d) => !d.funnel || d.funnel === f).length);
        } else {
          setStuck(null);
        }
      } catch {
        setStuck(null);
      }
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    void load(funnel, owner);
  }, [funnel, owner, load]);

  const maxCount = data ? Math.max(1, ...data.stages.map((s) => s.count)) : 1;
  const totalCount = data ? data.stages.reduce((a, b) => a + b.count, 0) : 0;

  return (
    <div className="space-y-4">
      {/* Фильтры */}
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-[11px] text-muted">
          Воронка
          <select
            value={funnel}
            onChange={(e) => setFunnel(e.target.value)}
            className="mt-0.5 block rounded-md border border-line bg-canvas px-2 py-1 text-sm"
          >
            {funnels.length === 0 && <option value={funnel}>{funnel}</option>}
            {funnels.map((f) => (
              <option key={f.code} value={f.code}>
                {f.title} · {f.active_deals}
              </option>
            ))}
          </select>
        </label>
        <label className="text-[11px] text-muted">
          Продавец
          <select
            value={owner}
            onChange={(e) => setOwner(e.target.value)}
            className="mt-0.5 block w-44 rounded-md border border-line bg-canvas px-2 py-1 text-sm"
          >
            <option value="">Все</option>
            {owners.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </label>
      </div>

      {status === "loading" && (
        <div className="rounded-xl border border-line bg-sunken p-6 text-sm text-muted">Загрузка…</div>
      )}
      {status === "error" && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line p-4">
          <span className="text-sm text-muted">Не удалось загрузить аналитику.</span>
          <button
            onClick={() => void load(funnel, owner)}
            className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-white"
          >
            Повторить
          </button>
        </div>
      )}

      {status === "ready" && data && totalCount === 0 && (
        <div className="rounded-xl border border-line p-6 text-sm text-muted">
          В этой воронке нет сделок — аналитика пуста (honest-empty).
        </div>
      )}

      {status === "ready" && data && totalCount > 0 && (
        <>
          {/* Плитки сверху */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="rounded-xl border border-line p-4">
              <div className="text-[11px] uppercase tracking-wide text-muted">Взвеш. прогноз</div>
              <div className="mt-1 text-lg font-bold text-money tabular-nums">
                {formatByn(data.forecast_weighted)}
              </div>
              <div className="text-[11px] text-faint">сумма amount × вероятность нетерминальных стадий</div>
            </div>
            <div className="rounded-xl border border-line p-4">
              <div className="text-[11px] uppercase tracking-wide text-muted">Средний цикл won</div>
              <div className="mt-1 text-lg font-bold text-ink tabular-nums">
                {data.avg_cycle_days != null ? `${data.avg_cycle_days} дн` : "—"}
              </div>
              <div className="text-[11px] text-faint">
                по {data.won_count} выигранным сделкам в воронке (от создания до won)
              </div>
            </div>
            <div className="rounded-xl border border-line p-4">
              <div className="text-[11px] uppercase tracking-wide text-muted">Висяки (≥14 дн)</div>
              <div className="mt-1 text-lg font-bold text-ink tabular-nums">
                {stuck != null ? stuck : "—"}
              </div>
              <div className="text-[11px] text-faint">сделки в стадии дольше 14 дней (?stuck_days=14)</div>
            </div>
          </div>

          {/* Конверсия переход→переход + время на этапе (история DealStageEvent за окно
              периода) — видно сразу при входе, без прокрутки к воронке ниже. */}
          <div className="rounded-xl border border-line p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-[13px] font-bold text-ink">Конверсия и время на этапах</h3>
              <div className="flex flex-wrap items-center gap-2">
                <div className="flex items-center gap-0.5 rounded-lg border border-line bg-canvas p-0.5">
                  {METRIC_PERIODS.map((p) => (
                    <button
                      key={p.key}
                      onClick={() => {
                        setMetricPeriod(p.key);
                        setRangeFrom("");
                        setRangeTo("");
                      }}
                      className={clsx(
                        "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                        metricPeriod === p.key
                          ? "bg-accent-soft text-accent-ink"
                          : "text-muted hover:text-ink",
                      )}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-1">
                  <input
                    type="date"
                    value={rangeFrom}
                    onChange={(e) => setRangeFrom(e.target.value)}
                    aria-label="Начало диапазона"
                    className="rounded-md border border-line bg-canvas px-1.5 py-1 text-xs text-muted"
                  />
                  <span className="text-xs text-faint">—</span>
                  <input
                    type="date"
                    value={rangeTo}
                    onChange={(e) => setRangeTo(e.target.value)}
                    aria-label="Конец диапазона"
                    className="rounded-md border border-line bg-canvas px-1.5 py-1 text-xs text-muted"
                  />
                  <button
                    onClick={() => {
                      if (!rangeFrom || !rangeTo) return;
                      setMetricPeriod("range");
                      setRangeApplyToken((n) => n + 1);
                    }}
                    disabled={!rangeFrom || !rangeTo}
                    className="rounded-md border border-line px-2 py-1 text-xs font-medium text-muted hover:bg-sunken disabled:opacity-40"
                  >
                    Применить
                  </button>
                </div>
              </div>
            </div>

            {metricsStatus === "loading" && (
              <div className="text-[12px] text-faint">Загрузка…</div>
            )}
            {metricsStatus === "error" && (
              <div className="flex items-center justify-between gap-3 text-[12px] text-muted">
                <span>Не удалось загрузить график.</span>
                <button
                  onClick={() => void loadMetrics(funnel, owner, metricPeriod, rangeFrom, rangeTo)}
                  className="rounded-lg bg-accent px-2.5 py-1 text-[11px] font-semibold text-white"
                >
                  Повторить
                </button>
              </div>
            )}
            {metricsStatus === "ready" && metrics && (
              <>
                <div className="mb-3 text-[11px] text-faint">
                  {metrics.date_from} — {metrics.date_to}
                </div>
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                  {/* Конверсия переход→переход */}
                  <div>
                    <div className="mb-2 text-[11px] uppercase tracking-wide text-muted">
                      Конверсия перехода
                    </div>
                    <div className="space-y-2">
                      {metrics.stages.slice(0, -1).map((s, idx) => {
                        const next = metrics.stages[idx + 1];
                        return (
                          <div key={s.id} className="flex items-center gap-2 text-[11px]">
                            <span className="w-32 shrink-0 truncate text-muted" title={`${s.title} → ${next.title}`}>
                              {s.title} →
                            </span>
                            <div className="h-2.5 flex-1 overflow-hidden rounded bg-sunken">
                              {s.conv_next_pct != null && (
                                <div
                                  className="h-full bg-emerald-500"
                                  style={{ width: `${s.conv_next_pct}%` }}
                                />
                              )}
                            </div>
                            <span className="w-16 shrink-0 text-right font-semibold tabular-nums">
                              {s.conv_next_pct != null ? (
                                <span className="text-emerald-600">{s.conv_next_pct}%</span>
                              ) : (
                                <span className="text-faint">нет данных</span>
                              )}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* Время на этапе */}
                  <div>
                    <div className="mb-2 text-[11px] uppercase tracking-wide text-muted">
                      Среднее время на этапе
                    </div>
                    <div className="space-y-2">
                      {(() => {
                        const maxDays = Math.max(
                          1,
                          ...metrics.stages.map((s) => s.avg_time_days ?? 0),
                        );
                        return metrics.stages.map((s) => (
                          <div key={s.id} className="flex items-center gap-2 text-[11px]">
                            <span className="w-32 shrink-0 truncate text-muted" title={s.title}>
                              {s.title}
                            </span>
                            <div className="h-2.5 flex-1 overflow-hidden rounded bg-sunken">
                              {s.avg_time_days != null && (
                                <div
                                  className="h-full"
                                  style={{
                                    width: `${(s.avg_time_days / maxDays) * 100}%`,
                                    background: s.color,
                                  }}
                                />
                              )}
                            </div>
                            <span className="w-16 shrink-0 text-right font-semibold tabular-nums text-ink">
                              {s.avg_time_days != null ? `${s.avg_time_days} дн` : (
                                <span className="font-normal text-faint">нет данных</span>
                              )}
                            </span>
                          </div>
                        ));
                      })()}
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>

          {/* S3-6: Маржа воронки — взвеш. валовая прибыль и маржа% (BYN), honest-баннер при null */}
          <div className="rounded-xl border border-line p-4">
            <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-[13px] font-bold text-ink">Маржа воронки</h3>
              {margin && (
                <span className="rounded-md bg-sunken px-1.5 py-0.5 text-[11px] font-semibold text-muted">
                  оценка по {margin.deals_priced} из {margin.deals_total} сделкам
                </span>
              )}
            </div>
            {!margin ? (
              <div className="text-[12px] text-faint">Прогноз маржи недоступен.</div>
            ) : (
              <>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <div>
                    <div className="text-[11px] uppercase tracking-wide text-muted">Выручка взвеш.</div>
                    <div className="mt-1 text-lg font-bold text-ink tabular-nums">
                      {formatByn(margin.revenue_weighted)}
                    </div>
                    <div className="text-[11px] text-faint">цена клиенту × вероятность стадии</div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-wide text-muted">Вал. прибыль взвеш.</div>
                    <div className="mt-1 text-lg font-bold text-money tabular-nums">
                      {margin.gross_weighted != null ? formatByn(margin.gross_weighted) : "—"}
                    </div>
                    <div className="text-[11px] text-faint">(цена − landed себес) × вероятность</div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-wide text-muted">Маржа %</div>
                    <div className="mt-1 text-lg font-bold text-ink tabular-nums">
                      {margin.margin_pct_blended != null ? `${margin.margin_pct_blended}%` : "—"}
                    </div>
                    <div className="text-[11px] text-faint">вал. прибыль / выручка (взвеш.)</div>
                  </div>
                </div>
                {margin.gross_weighted == null && (
                  <div className="mt-2 text-[11px] text-faint">
                    {margin.reason ||
                      "Себестоимость закупок не подключена — валовая прибыль не рассчитана."}{" "}
                    Выручка показана; маржа появится после интеграции landed cost (procurement).
                  </div>
                )}
              </>
            )}
          </div>

          {/* Воронкообразная визуализация: стадия + count-полоса + сумма/взвеш + возраст + конверсия */}
          <div className="space-y-2">
            {data.stages.map((s, idx) => (
              <div key={s.id} className="rounded-xl border border-line p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="inline-block h-2.5 w-2.5 rounded" style={{ background: s.color }} />
                    <span className="text-[13px] font-semibold text-ink">{s.title}</span>
                    <span className="text-[11px] text-muted">
                      {s.count} {s.count === 1 ? "сделка" : "сделок"}
                    </span>
                  </div>
                  <div className="text-[12px] text-muted">
                    <span className="font-semibold text-ink">{formatByn(s.sum)}</span>
                    {" · взвеш. "}
                    <span className="font-semibold text-money">{formatByn(s.weighted)}</span>
                    {s.avg_age_days != null && (
                      <>
                        {" · "}
                        <span>возраст {s.avg_age_days} дн</span>
                      </>
                    )}
                  </div>
                </div>
                {/* «Воронка» — полоса по доле count */}
                <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded bg-sunken">
                  <div
                    className="h-full"
                    style={{
                      width: `${(s.count / maxCount) * 100}%`,
                      background: s.color,
                    }}
                  />
                </div>
                {/* Конверсия в следующую стадию */}
                {idx < data.stages.length - 1 && (
                  <div className="mt-2 flex items-center gap-2 text-[11px] text-muted">
                    <span>конверсия → {data.stages[idx + 1].title}:</span>
                    {s.next_conv_pct != null ? (
                      <>
                        <div className="h-1 max-w-[260px] flex-1 overflow-hidden rounded bg-sunken">
                          <div
                            className="h-full bg-emerald-500"
                            style={{ width: `${s.next_conv_pct}%` }}
                          />
                        </div>
                        <span className="w-9 text-right font-semibold text-emerald-600 tabular-nums">
                          {s.next_conv_pct}%
                        </span>
                      </>
                    ) : (
                      <span className="text-faint">истории нет — honest-empty</span>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
