"use client";

import { Plus, Trophy } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  contributionShare,
  createWorker,
  fetchPayroll,
  fetchWorkers,
  formatByn,
  formatNh,
  type Payroll,
  totalContribution,
  type Worker,
} from "@/lib/production-vyrabotka";

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className="mt-1 text-2xl font-bold text-ink">{value}</div>
    </div>
  );
}

export function VyrabotkaTable({ initial }: { initial: Payroll | null }) {
  const [payroll, setPayroll] = useState<Payroll | null>(initial);
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [name, setName] = useState("");
  const [salary, setSalary] = useState("");
  const [days, setDays] = useState("");
  const [nh, setNh] = useState("");
  const [nameError, setNameError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(initial ? "" : "Выработка неизвестна. Повторите загрузку.");
  const sending = useRef(false);
  const readRequest = useRef(0);
  const [reading, setReading] = useState(true);

  const refresh = useCallback(async () => {
    const request = ++readRequest.current;
    setReading(true);
    try {
      const [p, w] = await Promise.all([fetchPayroll(true), fetchWorkers(true)]);
      if (request !== readRequest.current) return;
      setPayroll(p); setWorkers(w); setError("");
    } catch {
      if (request !== readRequest.current) return;
      setPayroll(null); setError("Не удалось загрузить выработку. Итоги и список сборщиков неизвестны.");
    } finally {
      if (request === readRequest.current) setReading(false);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    void Promise.resolve().then(() => { if (alive) void refresh(); });
    return () => { alive = false; readRequest.current += 1; };
  }, [refresh]);

  const total = totalContribution(payroll?.rows ?? []);

  async function onAdd() {
    if (sending.current) return;
    if (!name.trim()) {
      setNameError(true);
      setTimeout(() => setNameError(false), 900);
      return;
    }
    sending.current = true; setBusy(true); setError("");
    // An older read must not erase a later write acknowledgement or failure.
    readRequest.current += 1; setReading(false);
    try {
    const created = await createWorker({
      name: name.trim(),
      salary: Number(salary.replace(",", ".")) || 0,
      days_worked: Number(days) || 0,
      nh_output: Number(nh.replace(",", ".")) || 0,
    });
    if (!created) throw new Error("Добавление сборщика не подтверждено. Поля сохранены. Обновите табель и проверьте результат перед повтором.");
    setName("");
    setSalary("");
    setDays("");
    setNh("");
    await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Не удалось добавить сборщика."); }
    finally { sending.current = false; setBusy(false); }
  }

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="grid grid-cols-4 gap-3">
        <Kpi label="Выработка цеха" value={payroll ? `${formatNh(payroll.total_nh)} н.ч` : "—"} />
        <Kpi label="Оклад (база)" value={payroll ? formatByn(payroll.total_base) : "—"} />
        <Kpi label="Премия от н.ч" value={payroll ? formatByn(payroll.total_premium) : "—"} />
        <Kpi label="Плановый ФОТ" value={payroll ? formatByn(payroll.total_payroll) : "—"} />
      </div>
      {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
      <button disabled={busy || reading} onClick={() => void refresh()}>Обновить табель</button>

      <div className="mt-5 text-sm font-semibold text-ink">Табель и плановая оценка оплаты</div>
      <p className="mt-1 text-xs text-amber-700" role="note">
        Это управленческая оценка по фиксированным допущениям. Она не является начислением зарплаты, проводкой или расчётом налогов и взносов.
      </p>
      <div className="mt-2 overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Сборщик</th>
              <th className="px-4 py-2 text-right font-medium">Выработка</th>
              <th className="px-4 py-2 text-right font-medium">Оклад</th>
              <th className="px-4 py-2 text-right font-medium">Премия</th>
              <th className="px-4 py-2 text-right font-medium">Плановая сумма</th>
              <th className="px-4 py-2 text-right font-medium">Вклад</th>
            </tr>
          </thead>
          <tbody>
            {payroll?.rows.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-muted">
                  Табель пуст — добавьте сборщика
                </td>
              </tr>
            )}
            {(payroll?.rows ?? []).map((r, i) => (
              <tr key={r.id} className="border-b border-line last:border-0">
                <td className="px-4 py-2.5">
                  <span className="inline-flex items-center gap-1.5 text-muted">
                    {i === 0 && <Trophy size={14} className="text-amber-500" />}
                    {r.name}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-muted">
                  {formatNh(r.nh_output)} н.ч
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-muted">
                  {formatByn(r.base)}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-muted">
                  {formatByn(r.premium)}
                </td>
                <td className="px-4 py-2.5 text-right font-semibold tabular-nums text-ink">
                  {formatByn(r.total)}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-accent-ink">
                  {contributionShare(r, total)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-3">
          <input disabled={busy}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Имя сборщика"
            className={`min-w-0 flex-1 rounded-lg border bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent ${
              nameError ? "border-amber-500" : "border-line"
            }`}
          />
          <input disabled={busy}
            value={salary}
            onChange={(e) => setSalary(e.target.value)}
            inputMode="decimal"
            placeholder="Оклад BYN"
            className="w-28 shrink-0 rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent"
          />
          <input disabled={busy}
            value={days}
            onChange={(e) => setDays(e.target.value)}
            inputMode="numeric"
            placeholder="Дни"
            className="w-16 shrink-0 rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent"
          />
          <input disabled={busy}
            value={nh}
            onChange={(e) => setNh(e.target.value)}
            inputMode="decimal"
            placeholder="Н.ч"
            className="w-20 shrink-0 rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent"
          />
          <button
            onClick={onAdd}
            disabled={busy}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
          >
            <Plus size={16} /> Добавить
          </button>
        </div>
      </div>
      <p className="mt-2 text-xs text-muted">
        Оценка = оклад × отработанные дни / 22 + выработка (н.ч) × 6,25 BYN. Это допущения производственного планирования. Записей в табеле: {payroll ? workers.length : "неизвестно"}.
      </p>
    </div>
  );
}
