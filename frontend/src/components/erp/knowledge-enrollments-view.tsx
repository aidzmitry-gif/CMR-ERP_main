"use client";

import { useEffect, useState } from "react";

type EnrollmentStatus = "assigned" | "in_progress" | "completed" | "overdue";

interface CourseEnrollment {
  id: number;
  course_id: number;
  employee_name: string;
  status: EnrollmentStatus;
  progress: number;
  assigned_at: string | null;
  completed_at: string | null;
}

const STATUS_LABELS: Record<EnrollmentStatus, string> = {
  assigned: "Назначен",
  in_progress: "В процессе",
  completed: "Завершён",
  overdue: "Просрочен",
};

const STATUS_BADGE: Record<EnrollmentStatus, string> = {
  assigned: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300",
  in_progress: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  completed: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  overdue: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
};

const ENROLLMENT_STATUSES: EnrollmentStatus[] = ["assigned", "in_progress", "completed", "overdue"];

interface CreateForm {
  course_id: string;
  employee_name: string;
  assigned_at: string;
}

const EMPTY_FORM: CreateForm = {
  course_id: "",
  employee_name: "",
  assigned_at: "",
};

export function KnowledgeEnrollmentsView() {
  const [enrollments, setEnrollments] = useState<CourseEnrollment[]>([]);
  const [filterEmployee, setFilterEmployee] = useState("");
  const [filterStatus, setFilterStatus] = useState<EnrollmentStatus | "">("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<CreateForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const params = new URLSearchParams();
    if (filterEmployee) params.set("employee_name", filterEmployee);
    if (filterStatus) params.set("status", filterStatus);
    try {
      const res = await fetch(`/api/knowledge/enrollments?${params.toString()}`, {
        cache: "no-store",
      });
      if (res.ok) setEnrollments(await res.json());
    } catch {
      /* сеть недоступна — показываем пустой список */
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterEmployee, filterStatus]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const body: Record<string, string | number> = {
        course_id: Number(form.course_id),
        employee_name: form.employee_name,
      };
      if (form.assigned_at) body.assigned_at = form.assigned_at;

      const res = await fetch("/api/knowledge/enrollments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        setError(`Ошибка ${res.status}`);
      } else {
        setForm(EMPTY_FORM);
        setShowForm(false);
        await load();
      }
    } catch {
      setError("Ошибка сети");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-auto p-6">
      {/* Фильтры + кнопка создания */}
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="text"
          value={filterEmployee}
          onChange={(e) => setFilterEmployee(e.target.value)}
          placeholder="Фильтр по сотруднику"
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent"
        />

        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value as EnrollmentStatus | "")}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-accent"
        >
          <option value="">Все статусы</option>
          {ENROLLMENT_STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABELS[s]}
            </option>
          ))}
        </select>

        <button
          onClick={() => setShowForm(!showForm)}
          className="ml-auto rounded-lg bg-accent px-4 py-1.5 text-sm font-medium text-white hover:bg-accent/90"
        >
          {showForm ? "Отмена" : "+ Назначить курс"}
        </button>
      </div>

      {/* Форма создания */}
      {showForm && (
        <form
          onSubmit={handleCreate}
          className="rounded-xl border border-line bg-surface p-4 shadow-sm"
        >
          <h3 className="mb-4 text-sm font-semibold text-ink">Назначение курса сотруднику</h3>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs text-muted">ID курса *</label>
              <input
                required
                type="number"
                min={1}
                value={form.course_id}
                onChange={(e) => setForm({ ...form, course_id: e.target.value })}
                placeholder="1"
                className="w-full rounded-lg border border-line bg-sunken px-3 py-1.5 text-sm text-ink placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent"
              />
            </div>

            <div>
              <label className="mb-1 block text-xs text-muted">Сотрудник *</label>
              <input
                required
                value={form.employee_name}
                onChange={(e) => setForm({ ...form, employee_name: e.target.value })}
                placeholder="Иванов Иван"
                className="w-full rounded-lg border border-line bg-sunken px-3 py-1.5 text-sm text-ink placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent"
              />
            </div>

            <div>
              <label className="mb-1 block text-xs text-muted">Дата назначения</label>
              <input
                type="date"
                value={form.assigned_at}
                onChange={(e) => setForm({ ...form, assigned_at: e.target.value })}
                className="w-full rounded-lg border border-line bg-sunken px-3 py-1.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-accent"
              />
            </div>
          </div>

          {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

          <div className="mt-4 flex justify-end">
            <button
              type="submit"
              disabled={saving}
              className="rounded-lg bg-accent px-5 py-1.5 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-60"
            >
              {saving ? "Сохранение…" : "Назначить"}
            </button>
          </div>
        </form>
      )}

      {/* Таблица назначений */}
      <div className="overflow-x-auto rounded-xl border border-line bg-surface shadow-sm">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line bg-sunken text-xs text-muted">
              <th className="px-4 py-3 text-left font-medium">Сотрудник</th>
              <th className="px-4 py-3 text-left font-medium">Курс ID</th>
              <th className="px-4 py-3 text-left font-medium">Статус</th>
              <th className="px-4 py-3 text-left font-medium">Прогресс %</th>
              <th className="px-4 py-3 text-left font-medium">Назначен</th>
              <th className="px-4 py-3 text-left font-medium">Завершён</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {enrollments.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted">
                  Назначений нет
                </td>
              </tr>
            ) : (
              enrollments.map((e) => (
                <tr key={e.id} className="hover:bg-sunken/50">
                  <td className="px-4 py-3 font-medium text-ink">{e.employee_name}</td>
                  <td className="px-4 py-3 font-mono text-xs text-accent">{e.course_id}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_BADGE[e.status] ?? ""}`}
                    >
                      {STATUS_LABELS[e.status] ?? e.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-muted">{e.progress}%</td>
                  <td className="px-4 py-3 text-muted">{e.assigned_at ?? "—"}</td>
                  <td className="px-4 py-3 text-muted">{e.completed_at ?? "—"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
