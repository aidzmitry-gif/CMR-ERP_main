"use client";

import { useEffect, useRef, useState } from "react";

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

type EnrollmentFilters = {
  employee: string;
  status: EnrollmentStatus | "";
};

function enrollmentFilterKey(filters: EnrollmentFilters) {
  const params = new URLSearchParams();
  if (filters.employee) params.set("employee_name", filters.employee);
  if (filters.status) params.set("status", filters.status);
  return params.toString();
}

const EMPTY_FORM: CreateForm = {
  course_id: "",
  employee_name: "",
  assigned_at: "",
};

export function KnowledgeEnrollmentsView() {
  const [enrollmentResult, setEnrollmentResult] = useState<{ filterKey: string; rows: CourseEnrollment[] } | null>(null);
  const [filterEmployee, setFilterEmployee] = useState("");
  const [filterStatus, setFilterStatus] = useState<EnrollmentStatus | "">("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<CreateForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listError, setListError] = useState<{ filterKey: string; message: string } | null>(null);
  const [loadingFilterKey, setLoadingFilterKey] = useState<string | null>(null);
  const currentFilters = { employee: filterEmployee, status: filterStatus };
  const filtersRef = useRef<EnrollmentFilters>(currentFilters);
  const activeRequest = useRef<AbortController | null>(null);
  const requestVersion = useRef(0);
  const mounted = useRef(false);
  const currentFilterKey = enrollmentFilterKey(currentFilters);
  const currentResult = enrollmentResult?.filterKey === currentFilterKey ? enrollmentResult : null;
  const currentListError = listError?.filterKey === currentFilterKey ? listError.message : null;
  const isLoading = loadingFilterKey === currentFilterKey;

  async function load(filters: EnrollmentFilters = filtersRef.current) {
    if (!mounted.current) return;
    const filterKey = enrollmentFilterKey(filters);
    const version = ++requestVersion.current;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setLoadingFilterKey(filterKey);
    setListError(null);
    try {
      const res = await fetch(`/api/knowledge/enrollments?${filterKey}`, {
        cache: "no-store",
        signal: controller.signal,
      });
      if (!res.ok) {
        if (!controller.signal.aborted && mounted.current && version === requestVersion.current) {
          setListError({ filterKey, message: `Ошибка ${res.status}` });
        }
        return;
      }
      const rows = (await res.json()) as CourseEnrollment[];
      if (!controller.signal.aborted && mounted.current && version === requestVersion.current) {
        setEnrollmentResult({ filterKey, rows });
      }
    } catch {
      if (!controller.signal.aborted && mounted.current && version === requestVersion.current) {
        setListError({ filterKey, message: "Ошибка сети" });
      }
    } finally {
      if (!controller.signal.aborted && mounted.current && version === requestVersion.current) {
        setLoadingFilterKey(null);
      }
    }
  }

  function clearListForFilterChange() {
    requestVersion.current += 1;
    activeRequest.current?.abort();
    setLoadingFilterKey(null);
    setListError(null);
    setEnrollmentResult(null);
  }

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      activeRequest.current?.abort();
    };
  }, []);

  useEffect(() => {
    void load({ employee: filterEmployee, status: filterStatus });
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
        if (mounted.current) setError(`Ошибка ${res.status}`);
      } else if (mounted.current) {
        setForm(EMPTY_FORM);
        setShowForm(false);
        await load(filtersRef.current);
      }
    } catch {
      if (mounted.current) setError("Ошибка сети");
    } finally {
      if (mounted.current) setSaving(false);
    }
  }

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-auto p-6">
      {/* Фильтры + кнопка создания */}
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="text"
          value={filterEmployee}
          onChange={(e) => {
            const employee = e.target.value;
            filtersRef.current = { ...filtersRef.current, employee };
            clearListForFilterChange();
            setFilterEmployee(employee);
          }}
          placeholder="Фильтр по сотруднику"
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent"
        />

        <select
          value={filterStatus}
          onChange={(e) => {
            const status = e.target.value as EnrollmentStatus | "";
            filtersRef.current = { ...filtersRef.current, status };
            clearListForFilterChange();
            setFilterStatus(status);
          }}
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
        {currentListError && (
          <div role="alert" className="flex flex-wrap items-center gap-3 border-b border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            <span>{currentListError}</span>
            {currentResult && <span>Показаны ранее загруженные данные.</span>}
            <button
              type="button"
              onClick={() => void load(filtersRef.current)}
              disabled={isLoading}
              className="rounded border border-red-300 px-3 py-1 font-medium hover:bg-red-100 disabled:opacity-60"
            >
              Повторить
            </button>
          </div>
        )}
        {isLoading && currentResult && (
          <p role="status" className="px-4 py-2 text-xs text-muted">Обновление списка…</p>
        )}
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
            {!currentResult ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted">
                  {currentListError ? "Не удалось загрузить назначения" : "Загрузка списка…"}
                </td>
              </tr>
            ) : currentResult.rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted">
                  Назначений нет
                </td>
              </tr>
            ) : (
              currentResult.rows.map((e) => (
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
