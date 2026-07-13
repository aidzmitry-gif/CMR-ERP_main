"use client";

import {
  ArrowUpRight,
  Boxes,
  CheckCircle2,
  Recycle,
  RefreshCcw,
  Send,
  Truck,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { fetchManagersCached } from "@/components/kanban/deal-card";
import { submitPlan, upsertPlan } from "@/lib/api";
import { formatByn, formatNumber } from "@/lib/format";
import {
  assemble,
  calcActivity,
  concentration,
  confidenceBand,
  formatDateShort,
  funnelCoverage,
  mergeSaved,
  metricsFromPlan,
  monthPace,
  nextMonthKey,
  paceStatus,
  regularCycleCaption,
  reverseCount,
  toDrafts,
  verdictOf,
  weightedForecast,
  type ActivityInput,
  type PlanItemDraft,
  type PlanSources,
  type RegularRow,
  type SeverityTone,
} from "@/lib/plan-constructor";
import type { Manager } from "@/lib/types";

/**
 * Конструктор месячного плана продавца (П12 ТЗ) — первый таб `/crm/deals/planning`.
 *
 * Собирает план из трёх источников (GET /sales/plan-sources): сделки месяца (committed,
 * из логистики/закупок), постоянные клиенты (regulars, прогноз по циклу перезаказа) и
 * калькулятор новых по действиям (заявки/звонки × конверсия). Отправка «РОПу» бьёт по
 * тому же PlanTarget-механизму, что и вкладка «Согласование» (deal-plan-editor.tsx):
 * снапшот строк — в PlanItemIn (PUT /sales/plan-items), 5 метрик — через upsertPlan+submitPlan.
 */

type Status = "loading" | "error" | "ready";

const MONTH_NAMES = [
  "январь", "февраль", "март", "апрель", "май", "июнь",
  "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
];

function monthLabel(monthKey: string): string {
  const [y, m] = monthKey.split("-");
  return `${MONTH_NAMES[Number(m) - 1] ?? monthKey} ${y}`;
}

function savedDateLabel(createdAt?: string): string | null {
  if (!createdAt) return null;
  return formatDateShort(createdAt.slice(0, 10));
}

const DEFAULT_ACTIVITY: ActivityInput = {
  leads: 0,
  leadConvPct: 0,
  calls: 0,
  callConvPct: 0,
  avgCheck: 0,
  marginPct: 0,
};

export function PlanConstructor({ ownerId }: { ownerId: number }) {
  const [month, setMonth] = useState(() => nextMonthKey(new Date()));
  const [managers, setManagers] = useState<Manager[]>([]);
  const [ownerName, setOwnerName] = useState("");
  const [reloadTick, setReloadTick] = useState(0);
  const [status, setStatus] = useState<Status>("loading");
  const [sources, setSources] = useState<PlanSources | null>(null);
  const [drafts, setDrafts] = useState<PlanItemDraft[]>([]);
  const [activity, setActivity] = useState<ActivityInput>(DEFAULT_ACTIVITY);
  const [baseInput, setBaseInput] = useState("");
  const [planOverride, setPlanOverride] = useState<number | null>(null);
  const [usingSaved, setUsingSaved] = useState(false);
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState<{ ok: boolean; text: string } | null>(null);
  // Дата — только на клиенте после монтирования: маркер темпа зависит от «сегодня», а на
  // сервере и клиенте new Date() разошлись бы (гидратация). До монтирования темп не рисуем.
  const [now, setNow] = useState<Date | null>(null);

  // Продавцы — из общего кэша (карточки сделок); owner_id приходит пропсом с URL.
  // ponytail: имя↔owner_id пока не связаны (нет HR-справочника сотрудников).
  useEffect(() => {
    void fetchManagersCached().then((list) => {
      setManagers(list);
      setOwnerName((cur) => cur || list[0]?.name || "");
    });
  }, []);

  useEffect(() => setNow(new Date()), []);

  useEffect(() => {
    if (!ownerName) return;
    let ignore = false;
    setStatus("loading");
    const qs = new URLSearchParams({ month, owner: ownerName, owner_id: String(ownerId) });
    fetch(`/api/sales/plan-sources?${qs.toString()}`, { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error(String(res.status));
        return res.json() as Promise<PlanSources>;
      })
      .then((data) => {
        if (ignore) return;
        setSources(data);
        const hasSaved = data.saved_items.length > 0;
        setUsingSaved(hasSaved);
        setDrafts(hasSaved ? mergeSaved(toDrafts(data), data.saved_items) : toDrafts(data));
        setActivity({
          ...DEFAULT_ACTIVITY,
          avgCheck: data.defaults.avg_check ?? 0,
          marginPct: data.defaults.margin_pct ?? 0,
        });
        setBaseInput(data.base_gross != null ? String(data.base_gross) : "");
        setPlanOverride(null);
        setSendResult(null);
        setStatus("ready");
      })
      .catch(() => {
        if (!ignore) setStatus("error");
      });
    return () => {
      ignore = true;
    };
  }, [month, ownerName, ownerId, reloadTick]);

  const activityCalc = useMemo(() => calcActivity(activity), [activity]);
  const totals = useMemo(() => assemble(drafts, activityCalc.gross), [drafts, activityCalc.gross]);
  const base = sources?.base_gross ?? (baseInput.trim() ? Number(baseInput) || null : null);
  const verdict = verdictOf(base, totals.total);
  const need = verdict && !verdict.ok ? reverseCount(-verdict.diff, activity) : null;
  const footerValue = planOverride ?? Math.round(totals.total / 1000) * 1000;
  const scale = Math.max(totals.total, base ?? 0) || 1;

  // Пять сигналов прогноза (макет sales-plan-unified.html) — чистые расчёты из lib.
  const weighted = useMemo(() => weightedForecast(drafts, activityCalc.gross), [drafts, activityCalc.gross]);
  const band = useMemo(() => confidenceBand(totals.s1, weighted, totals.total), [totals.s1, weighted, totals.total]);
  const conc = useMemo(() => concentration(drafts, totals), [drafts, totals]);
  const pace = now ? monthPace(month, now) : null;
  const paceInfo = pace?.applicable && base != null ? paceStatus(totals.total, base, pace.frac) : null;
  const coverage =
    verdict && !verdict.ok
      ? funnelCoverage(activity.leads, (activity.avgCheck * activity.marginPct) / 100, -verdict.diff)
      : null;

  const regularMeta = useMemo(
    () => new Map<string, RegularRow>((sources?.regulars ?? []).map((r) => [r.counterparty, r])),
    [sources],
  );
  const committedDrafts = drafts.filter((d) => d.source === "committed");
  const regularDrafts = drafts.filter((d) => d.source === "regular");
  const inMonthDrafts = regularDrafts.filter((d) => regularMeta.get(d.ref)?.in_month);
  const outMonthDrafts = regularDrafts.filter((d) => !regularMeta.get(d.ref)?.in_month);

  function rebuildFromSources() {
    if (!sources) return;
    setDrafts(toDrafts(sources));
    setUsingSaved(false);
  }

  function toggleDraft(source: "committed" | "regular", ref: string, enabled: boolean) {
    setDrafts((prev) => prev.map((d) => (d.source === source && d.ref === ref ? { ...d, enabled } : d)));
  }

  function setDraftGross(source: "committed" | "regular", ref: string, gross: number) {
    setDrafts((prev) => prev.map((d) => (d.source === source && d.ref === ref ? { ...d, gross } : d)));
  }

  async function handleSubmit() {
    if (!sources) return;
    setSending(true);
    setSendResult(null);
    try {
      const items: PlanItemDraft[] = [
        ...drafts,
        {
          source: "activity",
          ref: "calc",
          title: "Новые по действиям",
          when_label: "расчёт по действиям",
          revenue: activityCalc.revenue,
          gross: activityCalc.gross,
          probability: 100,
          enabled: true,
        },
      ];
      const putQs = new URLSearchParams({ owner_id: String(ownerId), period_key: month });
      const putRes = await fetch(`/api/sales/plan-items?${putQs.toString()}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(items),
      });
      if (!putRes.ok) {
        setSendResult({ ok: false, text: "Не удалось сохранить план — источники недоступны" });
        return;
      }
      const metrics = metricsFromPlan({ totalGross: footerValue, activity: { ...activity, ...activityCalc } });
      const skipped: string[] = [];
      let done = 0;
      for (const m of metrics) {
        const plan = await upsertPlan({
          owner_id: ownerId,
          metric: m.metric,
          period_type: "month",
          period_key: month,
          target: m.target,
        });
        if (!plan) {
          skipped.push(m.metric);
          continue;
        }
        if (await submitPlan(plan.id)) done++;
        else skipped.push(m.metric);
      }
      if (done === metrics.length) setSendResult({ ok: true, text: `✓ Отправлено РОПу (${done} метрик)` });
      else if (done > 0)
        setSendResult({
          ok: false,
          text: `Отправлено частично (${done}/${metrics.length}) — пропущено: ${skipped.join(", ")}`,
        });
      else setSendResult({ ok: false, text: "Не удалось отправить ни одной метрики" });
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-[11px] text-muted">
          Месяц
          <input
            type="month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            className="mt-0.5 block rounded-md border border-line bg-canvas px-2 py-1 text-sm text-ink"
          />
        </label>
        <label className="text-[11px] text-muted">
          Продавец
          <select
            value={ownerName}
            onChange={(e) => setOwnerName(e.target.value)}
            className="mt-0.5 block min-w-[180px] rounded-md border border-line bg-canvas px-2 py-1 text-sm text-ink"
          >
            {managers.map((m) => (
              <option key={m.name} value={m.name}>
                {m.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {status === "loading" && (
        <div className="rounded-xl border border-line bg-sunken p-6 text-sm text-muted">Загрузка источников…</div>
      )}

      {status === "error" && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line p-4">
          <span className="text-sm text-muted">Источники недоступны — проверьте бэкенд</span>
          <button
            type="button"
            onClick={() => setReloadTick((t) => t + 1)}
            className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-white"
          >
            Повторить
          </button>
        </div>
      )}

      {status === "ready" && sources && (
        <>
          {usingSaved && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line bg-accent-soft px-4 py-2.5 text-[12.5px] text-accent-ink">
              <span>
                Сохранён черновик
                {(() => {
                  const label = savedDateLabel(sources.saved_items[0]?.created_at);
                  return label ? ` от ${label}` : "";
                })()}
                {/* входы калькулятора в снапшоте не хранятся (только его итог-строка) */}
                <span className="text-muted"> · блок «Новые» пересчитан заново</span>
              </span>
              <button
                type="button"
                onClick={rebuildFromSources}
                className="inline-flex items-center gap-1 rounded-lg border border-line bg-surface px-2.5 py-1 text-[11.5px] font-semibold text-ink hover:bg-sunken"
              >
                <RefreshCcw size={12} /> пересобрать из источников
              </button>
            </div>
          )}

          {/* Шапка: база / собрано / вердикт + стек-полоса с линией цели */}
          <div className="rounded-2xl bg-surface p-5 shadow-card">
            <div className="flex flex-wrap items-end gap-6">
              <div>
                <div className="text-[11px] text-muted">База — согласовано с РОПом</div>
                {sources.base_gross != null ? (
                  <div className="mt-0.5 text-2xl font-bold tabular-nums text-ink">
                    {formatByn(sources.base_gross)}
                  </div>
                ) : (
                  <input
                    type="number"
                    value={baseInput}
                    onChange={(e) => setBaseInput(e.target.value)}
                    placeholder="база не задана — впишите"
                    className="mt-0.5 w-44 rounded-lg border border-line bg-canvas px-2 py-1 text-lg font-bold tabular-nums text-ink outline-none focus:border-accent"
                  />
                )}
              </div>
              <div>
                <div className="text-[11px] text-muted">Собрано из источников</div>
                <div className="mt-0.5 text-2xl font-bold tabular-nums text-accent-ink">
                  {formatByn(totals.total)}
                </div>
              </div>
              <div>
                <div className="text-[11px] text-muted">Взвешенный прогноз</div>
                <div className="mt-0.5 text-2xl font-bold tabular-nums text-money">
                  {formatByn(weighted)}
                </div>
                <div className="text-[10px] text-faint">
                  приход товара — 90% · постоянные — по их вероятности · новые — как есть
                </div>
              </div>
              <div className="ml-auto text-right">
                {verdict == null ? (
                  <span className="inline-block rounded-full bg-sunken px-3.5 py-1.5 text-sm font-bold text-muted">
                    База не задана
                  </span>
                ) : verdict.ok ? (
                  <span className="inline-block rounded-full bg-emerald-50 px-3.5 py-1.5 text-sm font-bold text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300">
                    План набран
                  </span>
                ) : (
                  <span className="inline-block rounded-full bg-red-50 px-3.5 py-1.5 text-sm font-bold text-red-600 dark:bg-red-500/15 dark:text-red-300">
                    Дефицит {formatByn(-verdict.diff)}
                  </span>
                )}
                {verdict != null && (
                  <div className="mt-1.5 text-[11px] text-faint">
                    {verdict.ok
                      ? `перекрывают базу на ${formatByn(verdict.diff)}`
                      : `собрано ${base ? Math.round((totals.total / base) * 100) : 0}% базы`}
                  </div>
                )}
                {paceInfo != null && (
                  <div className="mt-1.5">
                    <span className={`inline-block rounded-md px-2 py-0.5 text-[10.5px] font-bold ${toneChip(paceInfo.tone)}`}>
                      {paceInfo.ahead
                        ? `↑ опережаете темп на ${formatByn(paceInfo.delta)}`
                        : `↓ отстаёте от темпа на ${formatByn(-paceInfo.delta)}`}
                    </span>
                  </div>
                )}
              </div>
            </div>

            <div className="relative mt-5">
              <div className="flex h-6 overflow-hidden rounded-xl bg-sunken">
                {totals.s1 > 0 && (
                  <div className="h-full bg-blue-500" style={{ width: `${(totals.s1 / scale) * 100}%` }} />
                )}
                {totals.s2 > 0 && (
                  <div className="h-full bg-emerald-500" style={{ width: `${(totals.s2 / scale) * 100}%` }} />
                )}
                {totals.s3 > 0 && (
                  <div className="h-full bg-amber-500" style={{ width: `${(totals.s3 / scale) * 100}%` }} />
                )}
                {base != null && totals.total < base && (
                  <div
                    className="h-full bg-red-200 dark:bg-red-500/25"
                    style={{ width: `${((base - totals.total) / scale) * 100}%` }}
                  />
                )}
              </div>
              {base != null && (
                <div className="absolute -top-1 bottom-[-4px] w-0.5 bg-ink" style={{ left: markerLeft(base, scale) }}>
                  <span className="absolute -top-4 left-1/2 -translate-x-1/2 whitespace-nowrap rounded bg-surface px-1 text-[10px] font-bold text-ink">
                    план РОПа
                  </span>
                </div>
              )}
              {paceInfo != null && (
                <div
                  className="absolute -top-1 bottom-[-4px] w-0.5 bg-accent"
                  style={{ left: markerLeft(Math.min(paceInfo.expected, scale), scale) }}
                >
                  <span className="absolute -bottom-4 left-1/2 -translate-x-1/2 whitespace-nowrap rounded bg-surface px-1 text-[9.5px] font-bold text-accent-ink">
                    сегодня
                  </span>
                </div>
              )}
            </div>

            {/* Полоса уверенности: почти наверняка (приход) → вероятно (взвеш.) → потолок (весь сбор).
                Один синий-градиент по убыванию уверенности — не путается с цветами источников выше. */}
            <div className="relative mt-6">
              <div className="flex h-2 overflow-hidden rounded bg-sunken">
                {band.guaranteed > 0 && (
                  <div className="h-full bg-blue-600" style={{ width: `${(band.guaranteed / scale) * 100}%` }} />
                )}
                {band.probable > band.guaranteed && (
                  <div
                    className="h-full bg-blue-400"
                    style={{ width: `${((band.probable - band.guaranteed) / scale) * 100}%` }}
                  />
                )}
                {band.ceiling > band.probable && (
                  <div
                    className="h-full bg-blue-200 dark:bg-blue-500/30"
                    style={{ width: `${((band.ceiling - band.probable) / scale) * 100}%` }}
                  />
                )}
              </div>
              {base != null && (
                <div
                  className="absolute -top-0.5 bottom-[-2px] w-0.5 bg-ink"
                  style={{ left: markerLeft(base, scale) }}
                />
              )}
            </div>
            <div className="mt-1.5 text-[11px] text-faint">
              Почти наверняка{" "}
              <b className="text-blue-700 dark:text-blue-300">{formatByn(band.guaranteed)}</b> · Вероятно{" "}
              <b className="text-blue-500 dark:text-blue-400">{formatByn(band.probable)}</b> · Потолок{" "}
              <b className="text-muted">{formatByn(band.ceiling)}</b>
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-4 text-[11px]">
              <LegendItem cls="bg-blue-500" label="📦 Сделки месяца" />
              <LegendItem cls="bg-emerald-500" label="♻ Постоянные" />
              <LegendItem cls="bg-amber-500" label="⚡ Новые (по действиям)" />
              <LegendItem cls="bg-red-200 dark:bg-red-500/25" label="дефицит" />
              {totals.total > 0 && (
                <span
                  className={`ml-auto inline-flex items-center rounded-lg px-2.5 py-1 text-[11.5px] font-bold ${toneChip(conc.tone)}`}
                >
                  {conc.label}
                </span>
              )}
            </div>
          </div>

          {/* 1. Сделки месяца */}
          <div className="overflow-hidden rounded-2xl bg-surface shadow-card">
            <SourceHeader
              icon={<Boxes size={18} />}
              iconCls="bg-blue-50 text-blue-600 dark:bg-blue-500/15 dark:text-blue-300"
              title="Сделки месяца"
              badge="из логистики + закупок"
              sub="Позиции, которые точно приедут в этом месяце"
              count={committedDrafts.filter((d) => d.enabled).length}
              unit="сдел."
              rev={committedDrafts.filter((d) => d.enabled).reduce((s, d) => s + d.revenue, 0)}
              pf={totals.s1}
              base={base}
            />
            {committedDrafts.length === 0 ? (
              <div className="p-4 text-sm text-muted">Сделок месяца из источников не найдено.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[680px] text-sm">
                  <thead>
                    <tr className="bg-sunken text-[10px] uppercase tracking-wide text-faint">
                      <th className="w-10 px-4 py-2" />
                      <th className="px-4 py-2 text-left font-semibold">Сделка</th>
                      <th className="px-4 py-2 text-left font-semibold">Когда</th>
                      <th className="px-4 py-2 text-right font-semibold">Выручка</th>
                      <th className="px-4 py-2 text-right font-semibold">План, вал. приб.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {committedDrafts.map((d) => (
                      <tr key={d.ref} className={`border-t border-line ${d.enabled ? "" : "opacity-40"}`}>
                        <td className="px-4 py-2.5">
                          <input
                            type="checkbox"
                            checked={d.enabled}
                            onChange={(e) => toggleDraft("committed", d.ref, e.target.checked)}
                            className="h-4 w-4 cursor-pointer accent-accent"
                            aria-label={`Учитывать ${d.title}`}
                          />
                        </td>
                        <td className="px-4 py-2.5 font-semibold text-ink">{d.title}</td>
                        <td className="px-4 py-2.5">
                          <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-md bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-600 dark:bg-amber-500/15 dark:text-amber-300">
                            <Truck size={12} /> {d.when_label}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-right tabular-nums text-ink">{formatByn(d.revenue)}</td>
                        <td className="px-4 py-2.5 text-right">
                          <input
                            type="number"
                            value={d.gross}
                            onChange={(e) => setDraftGross("committed", d.ref, Number(e.target.value) || 0)}
                            className="w-28 rounded-lg border border-line bg-surface px-2 py-1.5 text-right text-sm font-semibold tabular-nums text-ink outline-none focus:border-accent"
                            aria-label={`План прибыли ${d.title}`}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* 2. Постоянные клиенты */}
          <div className="overflow-hidden rounded-2xl bg-surface shadow-card">
            <SourceHeader
              icon={<Recycle size={18} />}
              iconCls="bg-emerald-50 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300"
              title="Постоянные клиенты"
              badge="прогноз по циклу перезаказа"
              sub={`${regularDrafts.length} клиентов в базе · ${inMonthDrafts.length} ждём в этом месяце, ${outMonthDrafts.length} — позже`}
              count={regularDrafts.filter((d) => d.enabled).length}
              unit="клиент."
              rev={regularDrafts.filter((d) => d.enabled).reduce((s, d) => s + d.revenue, 0)}
              pf={totals.s2}
              base={base}
            />
            {regularDrafts.length === 0 ? (
              <div className="p-4 text-sm text-muted">Постоянных клиентов не найдено.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-sm">
                  <thead>
                    <tr className="bg-sunken text-[10px] uppercase tracking-wide text-faint">
                      <th className="w-10 px-4 py-2" />
                      <th className="px-4 py-2 text-left font-semibold">Клиент</th>
                      <th className="px-4 py-2 text-left font-semibold">Ожид. заказ</th>
                      <th className="px-4 py-2 text-right font-semibold">Ср. чек</th>
                      <th className="px-4 py-2 text-right font-semibold">Вероятность</th>
                      <th className="px-4 py-2 text-right font-semibold">План, вал. приб.</th>
                    </tr>
                  </thead>
                  <tbody>
                    <GroupRow label={`Ожидаются в месяце — ${inMonthDrafts.length}`} tone="emerald" />
                    {inMonthDrafts.map((d) => (
                      <RegularTr
                        key={d.ref}
                        draft={d}
                        meta={regularMeta.get(d.ref)}
                        onToggle={(on) => toggleDraft("regular", d.ref, on)}
                        onGross={(v) => setDraftGross("regular", d.ref, v)}
                      />
                    ))}
                    <GroupRow
                      label={`Вне месяца — ${outMonthDrafts.length} · можно подтянуть раньше`}
                      tone="amber"
                    />
                    {outMonthDrafts.map((d) => (
                      <RegularTr
                        key={d.ref}
                        draft={d}
                        meta={regularMeta.get(d.ref)}
                        onToggle={(on) => toggleDraft("regular", d.ref, on)}
                        onGross={(v) => setDraftGross("regular", d.ref, v)}
                        pullBadge
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* 3. Новые — по действиям */}
          <div className="overflow-hidden rounded-2xl bg-surface shadow-card">
            <SourceHeader
              icon={<Zap size={18} />}
              iconCls="bg-amber-50 text-amber-600 dark:bg-amber-500/15 dark:text-amber-300"
              title="Новые — по действиям"
              badge="заявки + звонки"
              sub="Сколько сделок/прибыли даёт активность при вашей конверсии и среднем чеке"
              count={activityCalc.deals.toFixed(1)}
              unit="сдел."
              rev={activityCalc.revenue}
              pf={activityCalc.gross}
              base={base}
            />
            <div className="p-4">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <CalcField
                  label="Заявки от маркетинга, шт/мес"
                  value={activity.leads}
                  onChange={(v) => setActivity((c) => ({ ...c, leads: v }))}
                />
                <CalcField
                  label="Конверсия заявка → сделка, %"
                  value={activity.leadConvPct}
                  onChange={(v) => setActivity((c) => ({ ...c, leadConvPct: v }))}
                />
                <CalcField
                  label="Холодные звонки, шт/мес"
                  value={activity.calls}
                  onChange={(v) => setActivity((c) => ({ ...c, calls: v }))}
                />
                <CalcField
                  label="Конверсия звонок → сделка, %"
                  value={activity.callConvPct}
                  onChange={(v) => setActivity((c) => ({ ...c, callConvPct: v }))}
                />
                <CalcField
                  label="Средний чек, BYN"
                  value={activity.avgCheck}
                  onChange={(v) => setActivity((c) => ({ ...c, avgCheck: v }))}
                  badge={sources.defaults.avg_check != null ? "из истории" : undefined}
                />
                <CalcField
                  label="Маржа (вал. прибыль), %"
                  value={activity.marginPct}
                  onChange={(v) => setActivity((c) => ({ ...c, marginPct: v }))}
                  badge={
                    sources.defaults.margin_pct == null
                      ? undefined
                      : sources.defaults.margin_pct_source === "onec" ||
                          sources.defaults.margin_pct_source === "demo"
                        ? "из 1С"
                        : "из истории"
                  }
                />
              </div>

              <div className="mt-4 flex flex-wrap gap-3 border-t border-line pt-4">
                <div className="min-w-[120px] flex-1 rounded-xl bg-sunken p-3 text-center">
                  <div className="text-[11px] text-muted">Сделок (новые)</div>
                  <div className="mt-0.5 text-xl font-bold tabular-nums text-ink">
                    {activityCalc.deals.toFixed(1)}
                  </div>
                </div>
                <div className="min-w-[120px] flex-1 rounded-xl bg-accent-soft p-3 text-center">
                  <div className="text-[11px] text-accent-ink">Выручка</div>
                  <div className="mt-0.5 text-xl font-bold tabular-nums text-accent-ink">
                    {formatByn(activityCalc.revenue)}
                  </div>
                </div>
                <div className="min-w-[120px] flex-1 rounded-xl bg-money-soft p-3 text-center">
                  <div className="text-[11px] text-money">Вал. прибыль</div>
                  <div className="mt-0.5 text-xl font-bold tabular-nums text-money">
                    {formatByn(activityCalc.gross)}
                  </div>
                </div>
              </div>

              {verdict != null && verdict.ok && (
                <div className="mt-3 flex items-start gap-2 rounded-xl bg-emerald-50 p-3 text-[12.5px] text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300">
                  <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
                  <span>Источники закрывают план — дефицита нет.</span>
                </div>
              )}
              {verdict != null && !verdict.ok && (
                <div className="mt-3 rounded-xl bg-amber-50 p-3 text-[12.5px] text-amber-600 dark:bg-amber-500/15 dark:text-amber-300">
                  {need ? (
                    <>
                      Чтобы закрыть дефицит <b>{formatByn(-verdict.diff)}</b> нужно ещё{" "}
                      <b>~{need.needDeals} новых сделок</b>
                      {need.needLeads != null && (
                        <>
                          {" "}
                          → это <b>+{need.needLeads} заявок</b>
                        </>
                      )}
                      {need.needCalls != null && (
                        <>
                          {" "}
                          {need.needLeads != null ? "или" : "→ это"} <b>+{need.needCalls} звонков</b>
                        </>
                      )}
                      . Подними цифры в калькуляторе.
                    </>
                  ) : (
                    <>
                      Дефицит <b>{formatByn(-verdict.diff)}</b>, но при нулевом чеке/марже обратный счёт не
                      посчитать — впишите средний чек и маржу.
                    </>
                  )}
                  {coverage != null && (
                    // Только качественный вердикт по входу воронки — сколько ещё заявок нужно,
                    // уже сказано в обратном счёте выше (при текущей конверсии), без второго числа.
                    <div className="mt-2">
                      <span
                        className={`inline-block rounded-md px-2 py-0.5 text-[11.5px] font-bold ${toneChip(coverage.tone)}`}
                      >
                        {coverage.text}
                      </span>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Футер: план + отправка */}
          <div className="flex flex-wrap items-center gap-4 rounded-2xl bg-surface p-5 shadow-card">
            <div className="text-[12.5px] text-muted">
              Источники и калькулятор считаются вживую. План можно поднять выше — взять обязательство
              добрать.
            </div>
            <div className="ml-auto flex items-center gap-2">
              <span className="text-[12.5px] font-semibold text-muted">
                План на {monthLabel(month)} (вал. приб.)
              </span>
              <input
                type="number"
                value={footerValue}
                onChange={(e) => setPlanOverride(Number(e.target.value) || 0)}
                className="w-32 rounded-xl border border-line bg-surface px-3 py-2 text-right text-sm font-bold tabular-nums text-ink outline-none focus:border-accent"
              />
            </div>
            <button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={sending}
              className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-4 py-2.5 text-sm font-bold text-white hover:bg-accent-ink disabled:opacity-60"
            >
              <Send size={15} /> {sending ? "Отправка…" : "Отправить РОПу"}
            </button>
            {sendResult && (
              <span
                className={`text-[12.5px] font-bold ${
                  sendResult.ok ? "text-emerald-600 dark:text-emerald-300" : "text-amber-600 dark:text-amber-300"
                }`}
              >
                {sendResult.text}
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/** Позиция маркера в %, зажатая в [3,97]: центрированная подпись («план РОПа»/«сегодня»)
 * не вылезает за карточку на краях (дефицит → база на 100%, начало месяца → темп у 0%). */
function markerLeft(value: number, scale: number): string {
  return `${Math.min(Math.max((value / scale) * 100, 3), 97)}%`;
}

/** SeverityTone → пара классов (мягкий фон + читаемый текст, обе темы). */
function toneChip(tone: SeverityTone): string {
  if (tone === "red") return "bg-red-50 text-red-600 dark:bg-red-500/15 dark:text-red-300";
  if (tone === "amber") return "bg-amber-50 text-amber-600 dark:bg-amber-500/15 dark:text-amber-300";
  return "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300";
}

function LegendItem({ cls, label }: { cls: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-muted">
      <span className={`h-2.5 w-2.5 rounded-sm ${cls}`} />
      {label}
    </span>
  );
}

function SourceHeader({
  icon,
  iconCls,
  title,
  badge,
  sub,
  count,
  unit,
  rev,
  pf,
  base,
}: {
  icon: ReactNode;
  iconCls: string;
  title: string;
  badge: string;
  sub: string;
  count: number | string;
  unit: string;
  rev: number;
  pf: number;
  base: number | null;
}) {
  const share = base && base > 0 ? Math.round((pf / base) * 100) : null;
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
      <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${iconCls}`}>{icon}</span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2 font-bold text-ink">
          {title}
          <span className="rounded-md bg-sunken px-2 py-0.5 text-[10.5px] font-semibold text-muted">{badge}</span>
        </div>
        <div className="mt-0.5 text-[11px] text-faint">{sub}</div>
      </div>
      <div className="ml-auto flex gap-5 text-right">
        <StatCell label="в плане" value={`${count} ${unit}`} />
        <StatCell label="выручка" value={formatNumber(Math.round(rev))} />
        <StatCell label="вал. приб." value={formatNumber(Math.round(pf))} tone="money" />
        {share != null && <StatCell label="доля плана" value={`${share}%`} tone="accent" />}
      </div>
    </div>
  );
}

function StatCell({ label, value, tone }: { label: string; value: string; tone?: "money" | "accent" }) {
  const cls = tone === "money" ? "text-money" : tone === "accent" ? "text-accent-ink" : "text-ink";
  return (
    <div>
      <div className="text-[9.5px] uppercase tracking-wide text-faint">{label}</div>
      <div className={`mt-0.5 text-[15px] font-bold tabular-nums ${cls}`}>{value}</div>
    </div>
  );
}

function GroupRow({ label, tone }: { label: string; tone: "emerald" | "amber" }) {
  const cls = tone === "emerald" ? "text-emerald-600 dark:text-emerald-300" : "text-amber-600 dark:text-amber-300";
  return (
    <tr className="bg-sunken">
      <td colSpan={6} className={`border-t border-line px-4 py-2 text-[11px] font-bold uppercase tracking-wide ${cls}`}>
        {label}
      </td>
    </tr>
  );
}

function RegularTr({
  draft,
  meta,
  onToggle,
  onGross,
  pullBadge,
}: {
  draft: PlanItemDraft;
  meta: RegularRow | undefined;
  onToggle: (on: boolean) => void;
  onGross: (v: number) => void;
  pullBadge?: boolean;
}) {
  return (
    <tr className={`border-t border-line ${draft.enabled ? "" : "opacity-40"}`}>
      <td className="px-4 py-2.5">
        <input
          type="checkbox"
          checked={draft.enabled}
          onChange={(e) => onToggle(e.target.checked)}
          className="h-4 w-4 cursor-pointer accent-accent"
          aria-label={`Учитывать ${draft.title}`}
        />
      </td>
      <td className="px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-1.5 font-semibold text-ink">
          {draft.title}
          {pullBadge && (
            <span className="inline-flex items-center gap-0.5 rounded bg-accent-soft px-1.5 py-0.5 text-[10px] font-bold text-accent-ink">
              <ArrowUpRight size={11} /> подтянуть раньше
            </span>
          )}
        </div>
        <div className="text-[11px] text-faint">{meta ? regularCycleCaption(meta) : ""}</div>
      </td>
      <td className="px-4 py-2.5 text-[11px] text-muted">{draft.when_label}</td>
      <td className="px-4 py-2.5 text-right tabular-nums text-ink">{formatByn(draft.revenue)}</td>
      <td className="px-4 py-2.5 text-right">
        <span className="inline-block rounded bg-blue-50 px-1.5 py-0.5 text-[10.5px] font-bold text-blue-600 dark:bg-blue-500/15 dark:text-blue-300">
          {draft.probability}%
        </span>
      </td>
      <td className="px-4 py-2.5 text-right">
        <input
          type="number"
          value={draft.gross}
          onChange={(e) => onGross(Number(e.target.value) || 0)}
          className="w-28 rounded-lg border border-line bg-surface px-2 py-1.5 text-right text-sm font-semibold tabular-nums text-ink outline-none focus:border-accent"
          aria-label={`План прибыли ${draft.title}`}
        />
      </td>
    </tr>
  );
}

function CalcField({
  label,
  value,
  onChange,
  badge,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  badge?: string;
}) {
  return (
    <div className="rounded-xl border border-line bg-sunken px-3 py-2.5">
      <label className="mb-1.5 block text-[11px] text-muted">
        {label}
        {badge && (
          <span className="ml-1 rounded bg-accent-soft px-1 py-0.5 text-[9.5px] font-bold text-accent-ink">
            {badge}
          </span>
        )}
      </label>
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(Number(e.target.value) || 0)}
        className="w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-right text-sm font-bold tabular-nums text-ink outline-none focus:border-accent"
        aria-label={label}
      />
    </div>
  );
}
