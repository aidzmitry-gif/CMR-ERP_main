"use client";

import { useCallback, useEffect, useState } from "react";
import { decidePlan, fetchPlans, type PlanRow, submitPlan, upsertPlan } from "@/lib/api";
import { formatByn } from "@/lib/format";

/**
 * Встречное планирование РОП (П9 ТЗ) поверх `PlanTarget`: 16 метрик × период.
 *
 * Продавец редактирует draft-цели → отправляет на согласование (POST /plans/{id}/submit);
 * РОП согласует/отклоняет (POST /plans/{id}/decide). Факт берётся из /sales/kpis (если
 * метрика совпадает по key). Состояния: загрузка / ошибка+повтор / honest-empty (плана нет).
 *
 * Роль приходит снаружи (SSR через currentRole()). РОП-кнопки видны только при role=="РОП"
 * или супер-роли (director/admin) — серверная проверка прав остаётся за require_permission.
 */
const METRICS: { key: string; title: string; unit: "count" | "money" }[] = [
  { key: "calls", title: "Звонки", unit: "count" },
  { key: "cold_calls", title: "Холодные звонки", unit: "count" },
  { key: "leads", title: "Новые лиды", unit: "count" },
  { key: "deal_activities", title: "Активности по сделкам", unit: "count" },
  { key: "new_deals_count", title: "Новые сделки (шт)", unit: "count" },
  { key: "new_deals_amount", title: "Новые сделки (сумма)", unit: "money" },
  { key: "invoice_payment_conv", title: "Конверсия счёт→оплата %", unit: "count" },
  { key: "tenders_count", title: "Тендеры (шт)", unit: "count" },
  { key: "tenders_amount", title: "Тендеры (сумма)", unit: "money" },
  { key: "won_count", title: "Выигрыши (шт)", unit: "count" },
  { key: "won_amount", title: "Выигрыши (сумма)", unit: "money" },
  { key: "future_won", title: "Будущие выигрыши", unit: "money" },
  { key: "payments_vat", title: "Поступления", unit: "money" },
  { key: "shipments", title: "Отгрузки (сумма)", unit: "money" },
  { key: "gross_profit", title: "Валовая прибыль", unit: "money" },
  { key: "avg_deal", title: "Средняя сделка", unit: "money" },
];

const PERIODS: { id: PlanRow["period_type"]; label: string }[] = [
  { id: "day", label: "День" },
  { id: "week", label: "Неделя" },
  { id: "month", label: "Месяц" },
  { id: "quarter", label: "Квартал" },
  { id: "year", label: "Год" },
];

const STATUS_BADGE: Record<PlanRow["status"], { text: string; cls: string }> = {
  draft: { text: "черновик", cls: "bg-sunken text-muted" },
  pending_approval: { text: "на согласовании", cls: "bg-amber-100 text-amber-700" },
  approved: { text: "согласовано", cls: "bg-emerald-100 text-emerald-700" },
  rejected: { text: "отклонено", cls: "bg-red-100 text-red-700" },
};

type Fact = { key: string; actual: number; target: number; unit: string };

type Status = "loading" | "error" | "ready";

const todayMonth = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};

export function DealPlanEditor({
  ownerId,
  role,
}: {
  ownerId: number;
  role: string;
}) {
  const [periodType, setPeriodType] = useState<PlanRow["period_type"]>("month");
  const [periodKey, setPeriodKey] = useState(todayMonth());
  const [status, setStatus] = useState<Status>("loading");
  const [plans, setPlans] = useState<Record<string, PlanRow>>({});
  const [facts, setFacts] = useState<Record<string, Fact>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const isRop = role === "РОП" || role === "director" || role === "admin";

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const [rows, kpiRes] = await Promise.all([
        fetchPlans({ owner_id: ownerId, period_type: periodType, period_key: periodKey }),
        fetch(`/api/sales/kpis?period=${encodeURIComponent(periodType)}`, { cache: "no-store" }).then((r) =>
          r.ok ? r.json() : [],
        ),
      ]);
      const byMetric: Record<string, PlanRow> = {};
      for (const r of rows) byMetric[r.metric] = r;
      setPlans(byMetric);
      const fact: Record<string, Fact> = {};
      for (const k of kpiRes as Fact[]) fact[k.key] = k;
      setFacts(fact);
      // Инициализируем драфты из текущих планов (для редактирования).
      const d: Record<string, string> = {};
      for (const m of METRICS) {
        const p = byMetric[m.key];
        d[m.key] = p ? String(p.target) : "";
      }
      setDrafts(d);
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, [ownerId, periodType, periodKey]);

  useEffect(() => {
    void load();
  }, [load]);

  async function saveDraft(metric: string) {
    const value = Number(drafts[metric] || 0);
    setBusy(true);
    setNotice(null);
    const res = await upsertPlan({
      owner_id: ownerId,
      metric,
      period_type: periodType,
      period_key: periodKey,
      target: value,
    });
    setNotice(res ? `Сохранено: ${metric}` : `Не удалось сохранить ${metric} (план может быть уже согласован)`);
    setBusy(false);
    if (res) await load();
  }

  async function submit(metric: string) {
    const plan = plans[metric];
    if (!plan) return;
    setBusy(true);
    const ok = await submitPlan(plan.id);
    setNotice(ok ? `Отправлено на согласование: ${metric}` : "Нельзя отправить (не draft?)");
    setBusy(false);
    if (ok) await load();
  }

  async function decide(metric: string, approved: boolean) {
    const plan = plans[metric];
    if (!plan) return;
    setBusy(true);
    const ok = await decidePlan(plan.id, approved);
    setNotice(ok ? `${approved ? "Согласовано" : "Отклонено"}: ${metric}` : "Не удалось");
    setBusy(false);
    if (ok) await load();
  }

  return (
    <div className="space-y-3">
      {/* Шапка с периодом */}
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-[11px] text-muted">
          Тип периода
          <select
            value={periodType}
            onChange={(e) => setPeriodType(e.target.value as PlanRow["period_type"])}
            className="mt-0.5 block rounded-md border border-line bg-canvas px-2 py-1 text-sm"
          >
            {PERIODS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-[11px] text-muted">
          Ключ периода
          <input
            value={periodKey}
            onChange={(e) => setPeriodKey(e.target.value)}
            placeholder="2026-06 / 2026-W24 / 2026-Q2"
            className="mt-0.5 block w-40 rounded-md border border-line bg-canvas px-2 py-1 text-sm"
          />
        </label>
      </div>

      {notice && (
        <div className="rounded-lg border border-line bg-sunken px-3 py-2 text-[12.5px] text-ink">{notice}</div>
      )}

      {status === "loading" && (
        <div className="rounded-xl border border-line bg-sunken p-6 text-sm text-muted">Загрузка…</div>
      )}

      {status === "error" && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line p-4">
          <span className="text-sm text-muted">Не удалось загрузить план.</span>
          <button onClick={() => void load()} className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-white">
            Повторить
          </button>
        </div>
      )}

      {status === "ready" && (
        <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full min-w-[820px] text-sm">
            <thead>
              <tr className="border-b border-line text-[10px] uppercase tracking-wide text-faint">
                <th className="px-3 py-2 text-left font-semibold">Метрика</th>
                <th className="px-3 py-2 text-right font-semibold">План</th>
                <th className="px-3 py-2 text-right font-semibold">Факт</th>
                <th className="px-3 py-2 text-left font-semibold">Прогресс</th>
                <th className="px-3 py-2 text-center font-semibold">Статус</th>
                <th className="px-3 py-2 text-right font-semibold">Действия</th>
              </tr>
            </thead>
            <tbody>
              {METRICS.map((m) => {
                const plan = plans[m.key];
                const fact = facts[m.key];
                const target = plan ? plan.target : Number(drafts[m.key] || 0);
                const actual = fact ? fact.actual : 0;
                const pct = target > 0 ? Math.min(100, Math.round((actual / target) * 100)) : 0;
                const editable = !plan || plan.status === "draft" || plan.status === "rejected";
                const fmt = (v: number) =>
                  m.unit === "money" ? formatByn(v) : new Intl.NumberFormat("ru-RU").format(Math.round(v));
                const badge = plan ? STATUS_BADGE[plan.status] : { text: "не задан", cls: "bg-sunken text-faint" };
                return (
                  <tr key={m.key} className="border-b border-line last:border-0">
                    <td className="px-3 py-1.5 text-ink">{m.title}</td>
                    <td className="px-3 py-1.5 text-right">
                      {editable ? (
                        <input
                          type="number"
                          value={drafts[m.key] ?? ""}
                          onChange={(e) => setDrafts((d) => ({ ...d, [m.key]: e.target.value }))}
                          className="w-28 rounded-md border border-line bg-canvas px-2 py-1 text-right tabular-nums"
                        />
                      ) : (
                        <span className="tabular-nums text-ink">{fmt(target)}</span>
                      )}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-ink">{fact ? fmt(actual) : "—"}</td>
                    <td className="px-3 py-1.5">
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 max-w-[140px] flex-1 overflow-hidden rounded bg-sunken">
                          <div className="h-full bg-emerald-500" style={{ width: `${pct}%` }} />
                        </div>
                        <span className="w-9 text-right text-[11px] tabular-nums text-muted">{pct}%</span>
                      </div>
                    </td>
                    <td className="px-3 py-1.5 text-center">
                      <span className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${badge.cls}`}>
                        {badge.text}
                      </span>
                    </td>
                    <td className="px-3 py-1.5">
                      <div className="flex justify-end gap-1.5">
                        {editable && (
                          <button
                            onClick={() => void saveDraft(m.key)}
                            disabled={busy}
                            className="rounded-md bg-accent px-2.5 py-1 text-xs font-semibold text-white disabled:opacity-50"
                          >
                            Сохранить
                          </button>
                        )}
                        {plan?.status === "draft" && (
                          <button
                            onClick={() => void submit(m.key)}
                            disabled={busy}
                            className="rounded-md border border-line px-2.5 py-1 text-xs font-semibold text-muted hover:text-ink disabled:opacity-50"
                          >
                            На согласование
                          </button>
                        )}
                        {plan?.status === "pending_approval" && isRop && (
                          <>
                            <button
                              onClick={() => void decide(m.key, true)}
                              disabled={busy}
                              className="rounded-md bg-emerald-500 px-2.5 py-1 text-xs font-semibold text-white disabled:opacity-50"
                            >
                              Согласовать
                            </button>
                            <button
                              onClick={() => void decide(m.key, false)}
                              disabled={busy}
                              className="rounded-md border border-line px-2.5 py-1 text-xs font-semibold text-muted hover:text-red-600 disabled:opacity-50"
                            >
                              Отклонить
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-faint">
        Встречное планирование: продавец предлагает draft → отправляет РОПу → РОП согласует/отклоняет.
        Факт — из /sales/kpis для выбранного периода. Деньги в BYN.
      </p>
    </div>
  );
}
