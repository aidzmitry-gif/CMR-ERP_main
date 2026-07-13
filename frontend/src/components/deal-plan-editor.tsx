"use client";

import { useCallback, useEffect, useState } from "react";

import { fetchPlans, type PlanRow, submitPlan } from "@/lib/api";
import { formatByn } from "@/lib/format";
import { nextMonthKey } from "@/lib/plan-constructor";
import { decidePlanComment, reopenPlan } from "@/lib/planning-api";

/**
 * Панель согласования плана — нижняя половина единого экрана `/crm/deals/planning`
 * (макет sales-plan-unified.html, секция «План на согласовании»).
 *
 * Метрики берутся из того же PlanTarget-механизма, что заполняет конструктор сверху
 * (upsertPlan+submitPlan). 5 «живых» метрик (из конструктора) — всегда; 3 доп. (тендеры,
 * поступления, отгрузки) — под сворачивающейся кнопкой. Здесь НЕТ «Факта»/«Прогресса»:
 * это экран договорённости продавец↔РОП, факт живёт на доске /crm/deals (План/Факт).
 *
 * Продавец собрал и отправил план (кнопка в конструкторе) → строки становятся
 * «на согласовании» → РОП согласует/отклоняет с комментарием (decidePlanComment) →
 * согласованные становятся «Планом» на доске. Возврат в работу — reopenPlan: продавцу
 * «↻ Пересмотр», РОПу «Вернуть на доработку» (с причиной). role приходит из тоггла выше.
 */

type MetricKind = "control" | "result";

interface MetricDef {
  key: string;
  title: string;
  unit: "count" | "money";
  kind?: MetricKind;
}

/** 5 живых метрик — те же ключи, что metricsFromPlan (plan-constructor.ts). */
const LIVE_METRICS: MetricDef[] = [
  { key: "leads", title: "Новые лиды", unit: "count", kind: "control" },
  { key: "cold_calls", title: "Холодные звонки", unit: "count", kind: "control" },
  { key: "gross_profit", title: "Валовая прибыль", unit: "money", kind: "result" },
  { key: "new_deals_amount", title: "Новые сделки, сумма", unit: "money", kind: "result" },
  { key: "new_deals_count", title: "Новые сделки, шт", unit: "count", kind: "result" },
];

/** Доп. метрики — задаются вручную во вкладке «Согласование» (в конструкторе их нет). */
const EXTRA_METRICS: MetricDef[] = [
  { key: "tenders_amount", title: "Тендеры, сумма", unit: "money" },
  { key: "payments_vat", title: "Поступления с НДС", unit: "money" },
  { key: "shipments", title: "Отгрузки, сумма", unit: "money" },
];

const STATUS_BADGE: Record<PlanRow["status"], { text: string; cls: string }> = {
  draft: { text: "черновик", cls: "bg-sunken text-muted" },
  pending_approval: { text: "на согласовании", cls: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300" },
  approved: { text: "согласовано", cls: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300" },
  rejected: { text: "на доработку", cls: "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300" },
};

/** PlanTargetOut + rop_comment (бэк отдаёт его в согласовании; в общем PlanRow типа его нет). */
type PlanRowExt = PlanRow & { rop_comment?: string | null };

type Status = "loading" | "error" | "ready";

export function DealPlanEditor({ ownerId, role }: { ownerId: number; role: string }) {
  const [month, setMonth] = useState(() => nextMonthKey(new Date()));
  const [status, setStatus] = useState<Status>("loading");
  const [plans, setPlans] = useState<Record<string, PlanRowExt>>({});
  const [showMore, setShowMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  // Черновик комментария/причины РОПа по метрике (перед согласованием/отклонением/возвратом).
  const [comments, setComments] = useState<Record<string, string>>({});

  const isRop = role === "rop";

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const rows = (await fetchPlans({
        owner_id: ownerId,
        period_type: "month",
        period_key: month,
      })) as PlanRowExt[];
      const byMetric: Record<string, PlanRowExt> = {};
      for (const r of rows) byMetric[r.metric] = r;
      setPlans(byMetric);
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, [ownerId, month]);

  useEffect(() => {
    void load();
  }, [load]);

  async function decide(metric: string, approved: boolean) {
    const plan = plans[metric];
    if (!plan) return;
    setBusy(true);
    const ok = await decidePlanComment(plan.id, approved, comments[metric]);
    setNotice(ok ? `${approved ? "Согласовано" : "Отклонено"}: ${plan.metric}` : "Не удалось — проверьте права");
    setBusy(false);
    if (ok) {
      setComments((c) => ({ ...c, [metric]: "" }));
      await load();
    }
  }

  async function reopen(metric: string, withReason: boolean) {
    const plan = plans[metric];
    if (!plan) return;
    setBusy(true);
    const ok = await reopenPlan(plan.id, withReason ? comments[metric] : undefined);
    setNotice(ok ? "План возвращён в работу — поправьте и отправьте снова" : "Не удалось вернуть (план не согласован?)");
    setBusy(false);
    if (ok) {
      setComments((c) => ({ ...c, [metric]: "" }));
      await load();
    }
  }

  async function submit(metric: string) {
    const plan = plans[metric];
    if (!plan) return;
    setBusy(true);
    const ok = await submitPlan(plan.id);
    setNotice(ok ? `Отправлено на согласование: ${plan.metric}` : "Нельзя отправить (не черновик?)");
    setBusy(false);
    if (ok) await load();
  }

  async function submitAllDrafts() {
    const drafts = visible.map((m) => plans[m.key]).filter((p): p is PlanRowExt => !!p && p.status === "draft");
    if (drafts.length === 0) return;
    setBusy(true);
    let done = 0;
    for (const p of drafts) if (await submitPlan(p.id)) done++;
    setNotice(`Отправлено на согласование: ${done}/${drafts.length}`);
    setBusy(false);
    await load();
  }

  const visible = showMore ? [...LIVE_METRICS, ...EXTRA_METRICS] : LIVE_METRICS;
  const liveRows = LIVE_METRICS.map((m) => plans[m.key]).filter((p): p is PlanRowExt => !!p);
  const headerBadge =
    liveRows.length > 0 && liveRows.every((p) => p.status === "approved")
      ? { text: "согласовано", cls: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300" }
      : liveRows.some((p) => p.status === "pending_approval")
        ? { text: "на согласовании", cls: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300" }
        : { text: "черновик", cls: "bg-sunken text-muted" };
  const hasSellerDrafts = !isRop && visible.some((m) => plans[m.key]?.status === "draft");

  return (
    <div className="overflow-hidden rounded-2xl bg-surface shadow-card">
      {/* Шапка секции */}
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-violet-soft text-[16px] text-violet-ink">
          📋
        </span>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 font-bold text-ink">
            План на согласовании
            <span className={`rounded-md px-2 py-0.5 text-[10.5px] font-semibold ${headerBadge.cls}`}>
              {headerBadge.text}
            </span>
          </div>
          <p className="mt-0.5 max-w-[560px] text-[11.5px] text-faint">
            Показатели берутся из конструктора выше — РОП согласует их по строкам. После согласования эти
            цифры становятся «Планом» на доске сделок.
          </p>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-faint">
            <KindPill kind="control" /> — что продавец делает сам
            <KindPill kind="result" /> — что из этого получается
          </p>
        </div>
        <label className="ml-auto text-[11px] text-muted">
          Месяц плана
          <input
            type="month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            className="mt-0.5 block rounded-md border border-line bg-canvas px-2 py-1 text-sm text-ink"
          />
        </label>
      </div>

      {notice && (
        <div className="border-b border-line bg-sunken px-4 py-2 text-[12.5px] text-ink">{notice}</div>
      )}

      {status === "loading" && <div className="p-6 text-sm text-muted">Загрузка плана…</div>}

      {status === "error" && (
        <div className="flex flex-wrap items-center justify-between gap-3 p-4">
          <span className="text-sm text-muted">Не удалось загрузить план.</span>
          <button
            type="button"
            onClick={() => void load()}
            className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-white"
          >
            Повторить
          </button>
        </div>
      )}

      {status === "ready" && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="bg-sunken text-[10px] uppercase tracking-wide text-faint">
                <th className="px-4 py-2 text-left font-semibold">Метрика</th>
                <th className="px-4 py-2 text-right font-semibold">План</th>
                <th className="px-4 py-2 text-center font-semibold">Статус</th>
                <th className="px-4 py-2 text-right font-semibold">Действия</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((m) => {
                const plan = plans[m.key];
                const isExtra = EXTRA_METRICS.some((e) => e.key === m.key);
                const badge = plan ? STATUS_BADGE[plan.status] : { text: "не задан", cls: "bg-sunken text-faint" };
                const fmt = (v: number) =>
                  m.unit === "money" ? formatByn(v) : new Intl.NumberFormat("ru-RU").format(Math.round(v));
                return (
                  <tr key={m.key} className="border-t border-line">
                    <td className="px-4 py-2.5">
                      <div className="flex flex-wrap items-center gap-1.5 text-ink">
                        {m.title}
                        {m.kind && <KindPill kind={m.kind} />}
                        <span
                          className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide ${
                            isExtra ? "bg-sunken text-muted" : "bg-accent-soft text-accent-ink"
                          }`}
                        >
                          {isExtra ? "вручную" : "из конструктора"}
                        </span>
                      </div>
                      {plan?.rop_comment && (
                        <div className="mt-1 text-[11px] text-muted">
                          <b className="text-violet-ink">💬 РОП:</b> {plan.rop_comment}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-right font-bold tabular-nums text-ink">
                      {plan ? fmt(plan.target) : "—"}
                    </td>
                    <td className="px-4 py-2.5 text-center">
                      <span className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${badge.cls}`}>
                        {badge.text}
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      <RowActions
                        isRop={isRop}
                        plan={plan}
                        busy={busy}
                        comment={comments[m.key] ?? ""}
                        onComment={(v) => setComments((c) => ({ ...c, [m.key]: v }))}
                        onDecide={(ok) => void decide(m.key, ok)}
                        onReopen={(withReason) => void reopen(m.key, withReason)}
                        onSubmit={() => void submit(m.key)}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Подвал: сворачивание доп. метрик + отправка черновиков продавцом */}
      <div className="flex flex-wrap items-center gap-3 border-t border-line px-4 py-3">
        <span className="text-[11.5px] text-faint">5 метрик считаются из конструктора автоматически.</span>
        <button
          type="button"
          onClick={() => setShowMore((v) => !v)}
          className="text-[11.5px] font-semibold text-accent-ink hover:underline"
        >
          {showMore ? "− свернуть доп. метрики" : "+ ещё метрики вручную (тендеры, поступления, отгрузки…)"}
        </button>
        {hasSellerDrafts && (
          <button
            type="button"
            onClick={() => void submitAllDrafts()}
            disabled={busy}
            className="ml-auto rounded-xl bg-accent px-4 py-2 text-sm font-bold text-white hover:bg-accent-ink disabled:opacity-60"
          >
            Отправить план РОПу →
          </button>
        )}
      </div>
    </div>
  );
}

function KindPill({ kind }: { kind: MetricKind }) {
  return kind === "control" ? (
    <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300">
      управляю
    </span>
  ) : (
    <span className="rounded bg-violet-soft px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-violet-ink">
      результат
    </span>
  );
}

function RowActions({
  isRop,
  plan,
  busy,
  comment,
  onComment,
  onDecide,
  onReopen,
  onSubmit,
}: {
  isRop: boolean;
  plan: PlanRowExt | undefined;
  busy: boolean;
  comment: string;
  onComment: (v: string) => void;
  onDecide: (approved: boolean) => void;
  onReopen: (withReason: boolean) => void;
  onSubmit: () => void;
}) {
  if (!plan) {
    return <span className="block text-right text-[11.5px] text-faint">нет в плане</span>;
  }

  // ── РОП ──
  if (isRop) {
    if (plan.status === "pending_approval") {
      return (
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          <input
            value={comment}
            onChange={(e) => onComment(e.target.value)}
            placeholder="комментарий продавцу…"
            className="w-44 rounded-md border border-line bg-surface px-2 py-1 text-[12px] text-ink outline-none focus:border-accent"
          />
          <button
            type="button"
            onClick={() => onDecide(true)}
            disabled={busy}
            className="rounded-md bg-emerald-500 px-2.5 py-1 text-xs font-semibold text-white disabled:opacity-50"
          >
            Согласовать
          </button>
          <button
            type="button"
            onClick={() => onDecide(false)}
            disabled={busy}
            className="rounded-md border border-line px-2.5 py-1 text-xs font-semibold text-muted hover:text-red-600 disabled:opacity-50"
          >
            Отклонить
          </button>
        </div>
      );
    }
    if (plan.status === "approved") {
      return (
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          <input
            value={comment}
            onChange={(e) => onComment(e.target.value)}
            placeholder="причина возврата…"
            className="w-40 rounded-md border border-line bg-surface px-2 py-1 text-[12px] text-ink outline-none focus:border-accent"
          />
          <button
            type="button"
            onClick={() => onReopen(true)}
            disabled={busy}
            className="rounded-md border border-line px-2.5 py-1 text-xs font-semibold text-muted hover:text-red-600 disabled:opacity-50"
          >
            Вернуть на доработку
          </button>
        </div>
      );
    }
    return <span className="block text-right text-[11.5px] text-faint">ждёт продавца</span>;
  }

  // ── Продавец ──
  if (plan.status === "draft") {
    return (
      <div className="flex justify-end">
        <button
          type="button"
          onClick={onSubmit}
          disabled={busy}
          className="rounded-md border border-line px-2.5 py-1 text-xs font-semibold text-muted hover:text-ink disabled:opacity-50"
        >
          На согласование
        </button>
      </div>
    );
  }
  if (plan.status === "approved") {
    // Снять согласование может только РОП (право sales.deal.approve) — un-approve равносилен
    // отмене решения РОПа. Продавец просит пересмотр у РОПа (комментарием/в чате).
    return (
      <span className="block text-right text-[11.5px] font-semibold text-money">
        ✓ в плане · чтобы изменить — к РОПу
      </span>
    );
  }
  if (plan.status === "rejected") {
    return (
      <span className="block text-right text-[11.5px] text-red-600 dark:text-red-300">
        на доработку — поправьте в конструкторе и отправьте снова
      </span>
    );
  }
  return <span className="block text-right text-[11.5px] text-faint">у РОПа</span>;
}
