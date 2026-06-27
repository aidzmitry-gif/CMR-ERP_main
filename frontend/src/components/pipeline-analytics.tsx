"use client";

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

type Status = "loading" | "error" | "ready";

export function PipelineAnalytics({ initialFunnel = "new_clients" }: { initialFunnel?: string }) {
  const [funnels, setFunnels] = useState<FunnelRow[]>([]);
  const [funnel, setFunnel] = useState(initialFunnel);
  const [owner, setOwner] = useState("");
  const [status, setStatus] = useState<Status>("loading");
  const [data, setData] = useState<Analytics | null>(null);
  const [stuck, setStuck] = useState<number | null>(null);

  useEffect(() => {
    void fetchFunnels().then(setFunnels);
  }, []);

  const load = useCallback(async (f: string, o: string) => {
    setStatus("loading");
    try {
      const qs = new URLSearchParams({ funnel: f });
      if (o) qs.set("owner", o);
      const res = await fetch(`/api/sales/pipeline/analytics?${qs.toString()}`, { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      setData((await res.json()) as Analytics);
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
          Владелец (ФИО)
          <input
            value={owner}
            onChange={(e) => setOwner(e.target.value)}
            placeholder="все"
            className="mt-0.5 block w-44 rounded-md border border-line bg-canvas px-2 py-1 text-sm"
          />
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
