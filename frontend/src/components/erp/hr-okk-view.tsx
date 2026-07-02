"use client";

import { useCallback, useEffect, useState } from "react";

// ──────────────────────────── Типы ────────────────────────────

interface Employee {
  id: number;
  full_name: string;
  position: string;
}

interface OkkScore {
  id: number;
  employee_id: number;
  period: string;
  discipline: number;
  quality: number;
  service: number;
  teamwork: number;
  total: number;
  comment: string;
}

// ──────────────────────────── Вспомогательные компоненты ────────────────────────────

function TotalBadge({ total }: { total: number }) {
  const cls =
    total >= 90
      ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200"
      : total >= 70
        ? "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200"
        : "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200";
  return (
    <span className={`rounded-md px-2 py-0.5 text-xs font-semibold tabular-nums ${cls}`}>
      {total}
    </span>
  );
}

function ScoreInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted">
      {label}
      <input
        type="number"
        min={0}
        max={25}
        value={value}
        onChange={(e) => {
          const v = Math.max(0, Math.min(25, Number(e.target.value)));
          onChange(v);
        }}
        className="w-20 rounded-md border border-line bg-sunken px-2 py-1 text-sm tabular-nums text-ink"
      />
    </label>
  );
}

// ──────────────────────────── Главный вид ────────────────────────────

export function HrOkkView() {
  const [scores, setScores] = useState<OkkScore[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [periodFilter, setPeriodFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  // Форма добавления оценки
  const [showForm, setShowForm] = useState(false);
  const [empId, setEmpId] = useState("");
  const [period, setPeriod] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  });
  const [discipline, setDiscipline] = useState(0);
  const [quality, setQuality] = useState(0);
  const [service, setService] = useState(0);
  const [teamwork, setTeamwork] = useState(0);
  const [comment, setComment] = useState("");
  const [posting, setPosting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const loadScores = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const qs = periodFilter ? `?period=${encodeURIComponent(periodFilter)}` : "";
      const r = await fetch(`/api/hr/okk-scores${qs}`, { cache: "no-store" });
      if (!r.ok) throw new Error(String(r.status));
      setScores((await r.json()) as OkkScore[]);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [periodFilter]);

  useEffect(() => {
    loadScores();
  }, [loadScores]);

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

  const formTotal = discipline + quality + service + teamwork;

  const onSubmit = useCallback(async () => {
    if (!empId || !period) {
      setFormError("Укажите сотрудника и период");
      return;
    }
    setPosting(true);
    setFormError(null);
    try {
      const r = await fetch("/api/hr/okk-scores", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          employee_id: Number(empId),
          period,
          discipline,
          quality,
          service,
          teamwork,
          comment,
        }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? String(r.status));
      }
      setShowForm(false);
      setDiscipline(0);
      setQuality(0);
      setService(0);
      setTeamwork(0);
      setComment("");
      await loadScores();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Ошибка сохранения");
    } finally {
      setPosting(false);
    }
  }, [empId, period, discipline, quality, service, teamwork, comment, loadScores]);

  return (
    <main className="flex-1 overflow-auto p-6">
      {/* Заголовок */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-ink">ОКК · Оценки сотрудников</h1>
          <p className="mt-1 text-sm text-muted">
            Ежемесячные баллы по категориям: дисциплина, качество, сервис, командная работа (0–25 каждая, итого 0–100).
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setShowForm(true);
            setFormError(null);
          }}
          className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700"
        >
          + Добавить оценку
        </button>
      </div>

      {/* Фильтр по периоду */}
      <div className="mt-4 flex items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-muted">
          Период:
          <input
            type="month"
            value={periodFilter}
            onChange={(e) => setPeriodFilter(e.target.value)}
            className="rounded-md border border-line bg-sunken px-2 py-1 text-sm text-ink"
          />
        </label>
        {periodFilter && (
          <button
            type="button"
            onClick={() => setPeriodFilter("")}
            className="text-xs text-muted hover:text-ink"
          >
            Сбросить
          </button>
        )}
      </div>

      {/* Форма добавления */}
      {showForm && (
        <div className="mt-4 rounded-xl bg-surface p-4 shadow-card">
          <h2 className="mb-3 text-sm font-semibold text-ink">Новая оценка ОКК</h2>
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
                    {e.full_name}
                    {e.position ? ` · ${e.position}` : ""}
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
            <ScoreInput label="Дисциплина (0–25)" value={discipline} onChange={setDiscipline} />
            <ScoreInput label="Качество (0–25)" value={quality} onChange={setQuality} />
            <ScoreInput label="Сервис (0–25)" value={service} onChange={setService} />
            <ScoreInput label="Командная (0–25)" value={teamwork} onChange={setTeamwork} />
            <div className="flex flex-col gap-1 text-xs text-muted">
              Итого
              <TotalBadge total={formTotal} />
            </div>
          </div>
          <label className="mt-3 flex flex-col gap-1 text-xs text-muted">
            Комментарий
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              rows={2}
              maxLength={500}
              className="w-full rounded-md border border-line bg-sunken px-2 py-1 text-sm text-ink"
            />
          </label>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              disabled={posting}
              onClick={onSubmit}
              className="rounded-md bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-60"
            >
              {posting ? "…" : "Сохранить"}
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

      {/* Состояние */}
      {loading && <p className="mt-6 text-sm text-muted">Загрузка…</p>}
      {error && (
        <p className="mt-6 rounded-xl bg-surface p-4 text-sm text-rose-600 shadow-card">
          Не удалось загрузить оценки ОКК — проверьте подключение к HR-модулю.
        </p>
      )}

      {/* Таблица */}
      {!loading && !error && (
        <div className="mt-4 overflow-hidden rounded-xl bg-surface shadow-card">
          <table className="w-full text-sm">
            <thead className="border-b border-line text-left text-xs text-muted">
              <tr>
                <th className="px-4 py-2.5 font-medium">Сотрудник</th>
                <th className="px-4 py-2.5 font-medium">Период</th>
                <th className="px-4 py-2.5 text-center font-medium">Дисциплина</th>
                <th className="px-4 py-2.5 text-center font-medium">Качество</th>
                <th className="px-4 py-2.5 text-center font-medium">Сервис</th>
                <th className="px-4 py-2.5 text-center font-medium">Командная</th>
                <th className="px-4 py-2.5 text-center font-medium">Итого</th>
                <th className="px-4 py-2.5 font-medium">Комментарий</th>
              </tr>
            </thead>
            <tbody>
              {scores.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-muted">
                    Оценок ОКК пока нет.
                  </td>
                </tr>
              ) : (
                scores.map((s) => (
                  <tr key={s.id} className="border-b border-line last:border-0 hover:bg-sunken">
                    <td className="px-4 py-2.5 text-ink">{empName(s.employee_id)}</td>
                    <td className="px-4 py-2.5 tabular-nums text-muted">{s.period}</td>
                    <td className="px-4 py-2.5 text-center tabular-nums text-ink">{s.discipline}</td>
                    <td className="px-4 py-2.5 text-center tabular-nums text-ink">{s.quality}</td>
                    <td className="px-4 py-2.5 text-center tabular-nums text-ink">{s.service}</td>
                    <td className="px-4 py-2.5 text-center tabular-nums text-ink">{s.teamwork}</td>
                    <td className="px-4 py-2.5 text-center">
                      <TotalBadge total={s.total} />
                    </td>
                    <td className="max-w-xs truncate px-4 py-2.5 text-muted">{s.comment}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
