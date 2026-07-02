"use client";

import { useCallback, useEffect, useState } from "react";

// ──────────────────────────── Типы ────────────────────────────

interface Employee {
  id: number;
  full_name: string;
  position: string;
}

interface PayrollEntry {
  id: number;
  employee_id: number;
  period: string;
  amount_byn: string;
  status: string;
}

interface PayrollPeriodSummary {
  period: string;
  total_byn: string;
  count: number;
  pending_count: number;
}

type StatusFilter = "all" | "pending" | "paid";
type ViewMode = "summary" | "detail";

// ──────────────────────────── Вспомогательные компоненты ────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    pending: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
    paid: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200",
  };
  const labels: Record<string, string> = { pending: "ожидает", paid: "выплачено" };
  return (
    <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${styles[status] ?? "bg-sunken text-muted"}`}>
      {labels[status] ?? status}
    </span>
  );
}

// ──────────────────────────── Главный вид ────────────────────────────

export function HrPayrollView() {
  // Detail mode state
  const [entries, setEntries] = useState<PayrollEntry[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  // View mode
  const [viewMode, setViewMode] = useState<ViewMode>("summary");

  // Summary mode state
  const [summaries, setSummaries] = useState<PayrollPeriodSummary[]>([]);
  const [loadingSummary, setLoadingSummary] = useState(true);
  const [errorSummary, setErrorSummary] = useState(false);
  const [expandedPeriod, setExpandedPeriod] = useState<string | null>(null);
  const [periodEntries, setPeriodEntries] = useState<PayrollEntry[]>([]);
  const [loadingPeriod, setLoadingPeriod] = useState(false);

  // Форма начисления
  const [showForm, setShowForm] = useState(false);
  const [empId, setEmpId] = useState("");
  const [period, setPeriod] = useState(() => new Date().toISOString().slice(0, 7));
  const [amount, setAmount] = useState("");
  const [posting, setPosting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const loadEntries = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const qs = statusFilter !== "all" ? `?status=${statusFilter}` : "";
      const r = await fetch(`/api/hr/payroll${qs}`, { cache: "no-store" });
      if (!r.ok) throw new Error(String(r.status));
      setEntries((await r.json()) as PayrollEntry[]);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  const loadSummaries = useCallback(async () => {
    setLoadingSummary(true);
    setErrorSummary(false);
    try {
      const r = await fetch("/api/hr/payroll/summary", { cache: "no-store" });
      if (!r.ok) throw new Error(String(r.status));
      setSummaries((await r.json()) as PayrollPeriodSummary[]);
    } catch {
      setErrorSummary(true);
    } finally {
      setLoadingSummary(false);
    }
  }, []);

  const togglePeriod = useCallback(
    async (p: string) => {
      if (expandedPeriod === p) {
        setExpandedPeriod(null);
        setPeriodEntries([]);
        return;
      }
      setExpandedPeriod(p);
      setLoadingPeriod(true);
      try {
        const r = await fetch(`/api/hr/payroll?period=${encodeURIComponent(p)}`, {
          cache: "no-store",
        });
        if (!r.ok) throw new Error(String(r.status));
        setPeriodEntries((await r.json()) as PayrollEntry[]);
      } catch {
        setPeriodEntries([]);
      } finally {
        setLoadingPeriod(false);
      }
    },
    [expandedPeriod],
  );

  useEffect(() => {
    loadEntries();
  }, [loadEntries]);

  useEffect(() => {
    loadSummaries();
  }, [loadSummaries]);

  useEffect(() => {
    fetch("/api/hr/employees", { cache: "no-store" })
      .then((r) => (r.ok ? (r.json() as Promise<Employee[]>) : Promise.reject()))
      .then(setEmployees)
      .catch(() => {});
  }, []);

  const empName = useCallback(
    (id: number) => employees.find((e) => e.id === id)?.full_name ?? `#${id}`,
    [employees],
  );

  const onAccrue = useCallback(async () => {
    if (!empId || !period || !amount) {
      setFormError("Заполните все поля");
      return;
    }
    setPosting(true);
    setFormError(null);
    try {
      const r = await fetch("/api/hr/payroll/accrue", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ employee_id: Number(empId), period, amount_byn: amount }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? String(r.status));
      }
      setShowForm(false);
      setAmount("");
      await loadEntries();
      await loadSummaries();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Ошибка начисления");
    } finally {
      setPosting(false);
    }
  }, [empId, period, amount, loadEntries, loadSummaries]);

  const onPay = useCallback(
    async (entry: PayrollEntry) => {
      try {
        const r = await fetch("/api/hr/payroll/pay", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ employee_id: entry.employee_id, period: entry.period }),
        });
        if (!r.ok) throw new Error(String(r.status));
        await loadEntries();
        await loadSummaries();
        if (expandedPeriod === entry.period) {
          const r2 = await fetch(
            `/api/hr/payroll?period=${encodeURIComponent(entry.period)}`,
            { cache: "no-store" },
          );
          if (r2.ok) setPeriodEntries((await r2.json()) as PayrollEntry[]);
        }
      } catch {
        // молчаливый fallback — UI обновится при следующей загрузке
      }
    },
    [loadEntries, loadSummaries, expandedPeriod],
  );

  const fmtByn = (v: string) =>
    parseFloat(v).toLocaleString("ru-BY", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <main className="flex-1 overflow-auto p-6">
      {/* Заголовок + кнопка */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-ink">Начисления зарплаты</h1>
          <p className="mt-1 text-sm text-muted">Учёт начислений и выплат сотрудникам (BYN).</p>
        </div>
        <button
          type="button"
          onClick={() => { setShowForm(true); setFormError(null); }}
          className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700"
        >
          + Начислить
        </button>
      </div>

      {/* Вкладки режима */}
      <div className="mt-4 flex gap-2">
        {(["summary", "detail"] as ViewMode[]).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setViewMode(m)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              viewMode === m ? "bg-ink text-surface" : "bg-sunken text-muted hover:text-ink"
            }`}
          >
            {m === "summary" ? "Ведомость" : "Детально"}
          </button>
        ))}
      </div>

      {/* Форма начисления */}
      {showForm && (
        <div className="mt-4 rounded-xl bg-surface p-4 shadow-card">
          <h2 className="mb-3 text-sm font-semibold text-ink">Новое начисление</h2>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-xs text-muted">
              Сотрудник
              <select
                value={empId}
                onChange={(e) => setEmpId(e.target.value)}
                className="min-w-[14rem] rounded-md border border-line bg-sunken px-2 py-1 text-sm text-ink"
              >
                <option value="">— выберите —</option>
                {employees.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.full_name} {e.position ? `· ${e.position}` : ""}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted">
              Период (ГГГГ-ММ)
              <input
                type="month"
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
                className="rounded-md border border-line bg-sunken px-2 py-1 text-sm text-ink"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted">
              Сумма BYN
              <input
                type="number"
                step="0.01"
                min="0"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="1 500.00"
                className="w-36 rounded-md border border-line bg-sunken px-2 py-1 text-sm tabular-nums text-ink"
              />
            </label>
            <button
              type="button"
              disabled={posting}
              onClick={onAccrue}
              className="rounded-md bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60"
            >
              {posting ? "…" : "Начислить"}
            </button>
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="rounded-md bg-sunken px-3 py-1.5 text-sm text-muted"
            >
              Отмена
            </button>
          </div>
          {formError && <p className="mt-2 text-xs text-rose-600">{formError}</p>}
        </div>
      )}

      {/* ── Режим «Ведомость» ── */}
      {viewMode === "summary" && (
        <>
          {loadingSummary && <p className="mt-6 text-sm text-muted">Загрузка…</p>}
          {errorSummary && (
            <p className="mt-6 rounded-xl bg-surface p-4 text-sm text-rose-600 shadow-card">
              Не удалось загрузить ведомость — проверьте подключение к HR-модулю.
            </p>
          )}
          {!loadingSummary && !errorSummary && (
            <div className="mt-4 overflow-hidden rounded-xl bg-surface shadow-card">
              <table className="w-full text-sm">
                <thead className="border-b border-line text-left text-xs text-muted">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">Период</th>
                    <th className="px-4 py-2.5 font-medium">Сотрудников</th>
                    <th className="px-4 py-2.5 text-right font-medium">Итог, BYN</th>
                    <th className="px-4 py-2.5 font-medium">Ожидает</th>
                    <th className="px-4 py-2.5 font-medium">Выплачено</th>
                    <th className="px-4 py-2.5" />
                  </tr>
                </thead>
                <tbody>
                  {summaries.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-4 py-8 text-center text-muted">
                        Ведомость пуста.
                      </td>
                    </tr>
                  ) : (
                    summaries.flatMap((s) => {
                      const mainRow = (
                        <tr
                          key={s.period}
                          className="cursor-pointer border-b border-line last:border-0 hover:bg-sunken"
                          onClick={() => togglePeriod(s.period)}
                        >
                          <td className="px-4 py-2.5 font-medium text-ink">{s.period}</td>
                          <td className="px-4 py-2.5 tabular-nums text-muted">{s.count}</td>
                          <td className="px-4 py-2.5 text-right tabular-nums font-medium text-ink">
                            {fmtByn(s.total_byn)}
                          </td>
                          <td className="px-4 py-2.5">
                            {s.pending_count > 0 ? (
                              <span className="flex items-center gap-1 text-amber-700 dark:text-amber-300">
                                <span className="inline-block h-2 w-2 rounded-full bg-amber-400" />
                                {s.pending_count}
                              </span>
                            ) : (
                              <span className="flex items-center gap-1 text-emerald-700 dark:text-emerald-300">
                                <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" />
                                0
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-2.5 tabular-nums text-muted">
                            {s.count - s.pending_count}
                          </td>
                          <td className="px-4 py-2.5 text-right text-xs text-muted">
                            {expandedPeriod === s.period ? "▲" : "▼"}
                          </td>
                        </tr>
                      );
                      if (expandedPeriod !== s.period) return [mainRow];
                      const detailRow = (
                        <tr key={`${s.period}-detail`} className="bg-sunken">
                          <td colSpan={6} className="px-6 py-3">
                            {loadingPeriod ? (
                              <p className="text-xs text-muted">Загрузка…</p>
                            ) : periodEntries.length === 0 ? (
                              <p className="text-xs text-muted">Нет данных.</p>
                            ) : (
                              <table className="w-full text-xs">
                                <thead className="text-left text-muted">
                                  <tr>
                                    <th className="py-1 pr-4 font-medium">Сотрудник</th>
                                    <th className="py-1 pr-4 text-right font-medium">Сумма, BYN</th>
                                    <th className="py-1 pr-4 font-medium">Статус</th>
                                    <th className="py-1" />
                                  </tr>
                                </thead>
                                <tbody>
                                  {periodEntries.map((e) => (
                                    <tr key={e.id} className="border-t border-line">
                                      <td className="py-1 pr-4 text-ink">{empName(e.employee_id)}</td>
                                      <td className="py-1 pr-4 text-right tabular-nums text-ink">
                                        {fmtByn(e.amount_byn)}
                                      </td>
                                      <td className="py-1 pr-4">
                                        <StatusBadge status={e.status} />
                                      </td>
                                      <td className="py-1 text-right">
                                        {e.status === "pending" && (
                                          <button
                                            type="button"
                                            onClick={(ev) => {
                                              ev.stopPropagation();
                                              void onPay(e);
                                            }}
                                            className="rounded-md bg-emerald-600/10 px-2 py-0.5 text-xs font-medium text-emerald-700 hover:bg-emerald-600/20 dark:text-emerald-300"
                                          >
                                            Выплатить
                                          </button>
                                        )}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            )}
                          </td>
                        </tr>
                      );
                      return [mainRow, detailRow];
                    })
                  )}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* ── Режим «Детально» ── */}
      {viewMode === "detail" && (
        <>
          {/* Фильтр статуса */}
          <div className="mt-4 flex gap-2">
            {(["all", "pending", "paid"] as StatusFilter[]).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setStatusFilter(s)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  statusFilter === s
                    ? "bg-ink text-surface"
                    : "bg-sunken text-muted hover:text-ink"
                }`}
              >
                {s === "all" ? "Все" : s === "pending" ? "Ожидают" : "Выплачены"}
              </button>
            ))}
          </div>

          {loading && <p className="mt-6 text-sm text-muted">Загрузка…</p>}
          {error && (
            <p className="mt-6 rounded-xl bg-surface p-4 text-sm text-rose-600 shadow-card">
              Не удалось загрузить начисления — проверьте подключение к HR-модулю.
            </p>
          )}

          {!loading && !error && (
            <div className="mt-4 overflow-hidden rounded-xl bg-surface shadow-card">
              <table className="w-full text-sm">
                <thead className="border-b border-line text-left text-xs text-muted">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">Сотрудник</th>
                    <th className="px-4 py-2.5 font-medium">Период</th>
                    <th className="px-4 py-2.5 text-right font-medium">Сумма, BYN</th>
                    <th className="px-4 py-2.5 font-medium">Статус</th>
                    <th className="px-4 py-2.5 font-medium">Дата</th>
                    <th className="px-4 py-2.5" />
                  </tr>
                </thead>
                <tbody>
                  {entries.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-4 py-8 text-center text-muted">
                        Начислений пока нет.
                      </td>
                    </tr>
                  ) : (
                    entries.map((e) => (
                      <tr key={e.id} className="border-b border-line last:border-0 hover:bg-sunken">
                        <td className="px-4 py-2.5 text-ink">{empName(e.employee_id)}</td>
                        <td className="px-4 py-2.5 tabular-nums text-muted">{e.period}</td>
                        <td className="px-4 py-2.5 text-right tabular-nums text-ink font-medium">
                          {fmtByn(e.amount_byn)}
                        </td>
                        <td className="px-4 py-2.5">
                          <StatusBadge status={e.status} />
                        </td>
                        <td className="px-4 py-2.5 text-muted" />
                        <td className="px-4 py-2.5 text-right">
                          {e.status === "pending" && (
                            <button
                              type="button"
                              onClick={() => onPay(e)}
                              className="rounded-md bg-emerald-600/10 px-2 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-600/20 dark:text-emerald-300"
                            >
                              Выплатить
                            </button>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </main>
  );
}
