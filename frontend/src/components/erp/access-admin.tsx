"use client";

// Прототип «Управление доступом» (шаг 1 — доступ к модулям).
// Порт access-matrix.html в светлую тему приложения. Данные — demo
// (lib/access-admin-data.ts, снимок config/access.py). Записи в БД пока нет:
// кнопка «Сохранить снимок» отдаёт JSON для переноса на backend на шаге 2.

import { useMemo, useState } from "react";

import {
  ALL_SLUGS,
  DEFAULT_MATRIX,
  EMPLOYEES,
  MODULES,
  ROLES,
  type Employee,
  employeesByRole,
  makeUsername,
} from "@/lib/access-admin-data";

type Matrix = Record<string, Set<string>>;

function buildMatrix(): Matrix {
  const m: Matrix = {};
  for (const r of ROLES) m[r.slug] = new Set(DEFAULT_MATRIX[r.slug] ?? []);
  return m;
}

const TABS = [
  { key: "modules", label: "Доступ к модулям", ready: true },
  { key: "granular", label: "Гранулярные права", ready: false },
  { key: "templates", label: "Шаблонные роли", ready: false },
  { key: "exceptions", label: "Индивидуальные исключения", ready: false },
] as const;

export function AccessAdmin() {
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("modules");
  const [matrix, setMatrix] = useState<Matrix>(buildMatrix);
  const [employees, setEmployees] = useState<Employee[]>(EMPLOYEES);
  const [toast, setToast] = useState("");
  const [snapshot, setSnapshot] = useState<string | null>(null);

  const byRole = useMemo(() => employeesByRole(employees), [employees]);

  function flash(msg: string) {
    setToast(msg);
    window.setTimeout(() => setToast(""), 2500);
  }

  function toggle(role: string, slug: string) {
    const def = ROLES.find((r) => r.slug === role);
    if (def?.locked) return;
    setMatrix((prev) => {
      const next = { ...prev, [role]: new Set(prev[role]) };
      if (next[role].has(slug)) next[role].delete(slug);
      else next[role].add(slug);
      return next;
    });
  }

  function setRow(role: string, on: boolean) {
    setMatrix((prev) => ({ ...prev, [role]: new Set(on ? ALL_SLUGS : []) }));
  }

  function reset() {
    setMatrix(buildMatrix());
    flash("Сброшено к предложенному");
  }

  function exportSnapshot() {
    const obj = Object.fromEntries(
      ROLES.map((r) => [r.slug, ALL_SLUGS.filter((s) => matrix[r.slug].has(s))]),
    );
    setSnapshot(JSON.stringify(obj, null, 2));
  }

  return (
    <main className="flex-1 overflow-auto p-6">
      <h1 className="text-xl font-bold text-ink">Управление доступом</h1>
      <p className="mt-1 text-sm text-muted">
        Кто какие разделы системы видит. Шаг 1 — доступ к модулям по ролям. Прототип на
        demo-данных (снимок матрицы доступа); запись в БД подключим следующим шагом.
      </p>

      {/* Вкладки под будущие уровни прав (комбинация правил) */}
      <div className="mt-5 flex flex-wrap gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => t.ready && setTab(t.key)}
            disabled={!t.ready}
            className={[
              "relative -mb-px rounded-t-lg px-4 py-2 text-sm font-medium transition",
              tab === t.key
                ? "border-x border-t border-slate-200 bg-white text-brand-600"
                : t.ready
                  ? "text-slate-600 hover:text-ink"
                  : "cursor-not-allowed text-slate-300",
            ].join(" ")}
          >
            {t.label}
            {!t.ready && (
              <span className="ml-1.5 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-400">
                скоро
              </span>
            )}
          </button>
        ))}
      </div>

      {tab !== "modules" ? (
        <section className="mt-6 rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center">
          <p className="text-sm text-muted">
            Этот уровень — следующий шаг. Структура заложена: после согласования экрана
            «Доступ к модулям» сюда добавим гранулярные права (например{" "}
            <code className="rounded bg-slate-100 px-1 text-xs">sales.deal.approve</code>),
            шаблонные роли и индивидуальные исключения поверх ролей.
          </p>
        </section>
      ) : (
        <>
          {/* Быстрое добавление сотрудника */}
          <AddEmployee
            onAdd={(e) => {
              if (employees.some((x) => x.username === e.username)) {
                flash("Логин уже занят — поправьте");
                return;
              }
              setEmployees((prev) => [...prev, e]);
              flash(`Добавлен: ${e.full_name}`);
            }}
          />

          {/* Матрица роль × модуль */}
          <div className="mt-4 flex flex-wrap items-center gap-3 text-xs text-muted">
            <Legend className="border-emerald-500 bg-emerald-50 text-emerald-600">есть доступ</Legend>
            <Legend className="border-slate-200 bg-slate-50">нет доступа</Legend>
            <Legend className="border-amber-400 bg-amber-50 text-amber-500">
              директор — всегда всё (заблокировано)
            </Legend>
          </div>

          <div className="mt-3 overflow-auto rounded-2xl border border-slate-200 bg-white shadow-card">
            <table className="w-full border-separate border-spacing-0 text-[13px]">
              <thead>
                <tr>
                  <th className="sticky left-0 top-0 z-30 min-w-[230px] border-b border-r-2 border-slate-200 bg-slate-50 px-3 py-2 text-left font-semibold text-ink">
                    Роль / сотрудники
                  </th>
                  {MODULES.map((m) => (
                    <th
                      key={m.slug}
                      className="sticky top-0 z-20 border-b border-r border-slate-200 bg-slate-50 px-2 py-2 align-bottom"
                    >
                      <span className="mx-auto block h-[110px] [writing-mode:vertical-rl] rotate-180 text-xs font-medium text-slate-600">
                        {m.label}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ROLES.map((r) => {
                  const ppl = (byRole[r.slug] ?? []).map((e) => e.full_name).join(", ");
                  const cnt = ALL_SLUGS.filter((s) => matrix[r.slug].has(s)).length;
                  return (
                    <tr key={r.slug} className="group">
                      <td className="sticky left-0 z-10 border-b border-r-2 border-slate-200 bg-white px-3 py-2 align-top group-hover:bg-blue-50/40">
                        <div className="font-semibold text-ink">
                          {r.title} <span className="text-xs font-normal text-muted">· {cnt}</span>
                        </div>
                        <div className="mt-0.5 max-w-[210px] text-[11px] leading-snug text-muted">
                          {ppl || "— нет сотрудников —"}
                        </div>
                        {!r.locked && (
                          <div className="mt-1.5 flex gap-1.5">
                            <button
                              onClick={() => setRow(r.slug, true)}
                              className="rounded border border-slate-200 px-2 py-0.5 text-[10px] text-muted hover:border-brand-600 hover:text-ink"
                            >
                              все
                            </button>
                            <button
                              onClick={() => setRow(r.slug, false)}
                              className="rounded border border-slate-200 px-2 py-0.5 text-[10px] text-muted hover:border-brand-600 hover:text-ink"
                            >
                              очистить
                            </button>
                          </div>
                        )}
                      </td>
                      {MODULES.map((m) => {
                        const on = matrix[r.slug].has(m.slug);
                        const locked = r.locked;
                        return (
                          <td
                            key={m.slug}
                            onClick={() => toggle(r.slug, m.slug)}
                            className={[
                              "border-b border-r border-slate-200 p-0 text-center align-middle",
                              locked ? "cursor-not-allowed" : "cursor-pointer",
                            ].join(" ")}
                          >
                            <span
                              className={[
                                "mx-auto flex h-6 w-6 items-center justify-center rounded-md border text-xs transition",
                                locked
                                  ? "border-amber-400 bg-amber-50 text-amber-500"
                                  : on
                                    ? "border-emerald-500 bg-emerald-50 text-emerald-600"
                                    : "border-slate-200 bg-slate-50 text-transparent hover:border-brand-600",
                              ].join(" ")}
                            >
                              ✓
                            </span>
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Действия */}
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              onClick={exportSnapshot}
              className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:brightness-110"
            >
              💾 Сохранить снимок
            </button>
            <button
              onClick={reset}
              className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-ink hover:border-brand-600"
            >
              Сбросить к предложенному
            </button>
            {toast && <span className="text-sm font-medium text-emerald-600">{toast}</span>}
          </div>

          {snapshot && (
            <section className="mt-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-ink">
                  Снимок матрицы (JSON) — для переноса на backend
                </h2>
                <button
                  onClick={() => {
                    void navigator.clipboard.writeText(snapshot).then(() => flash("Скопировано ✓"));
                  }}
                  className="rounded-lg border border-slate-200 px-3 py-1 text-xs text-ink hover:border-brand-600"
                >
                  Копировать
                </button>
              </div>
              <pre className="max-h-72 overflow-auto rounded-lg bg-slate-900 p-3 text-[12px] leading-relaxed text-slate-100 thin-scroll">
                {snapshot}
              </pre>
            </section>
          )}
        </>
      )}
    </main>
  );
}

function Legend({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block h-3.5 w-3.5 rounded border ${className}`} />
      {children}
    </span>
  );
}

function AddEmployee({ onAdd }: { onAdd: (e: Employee) => void }) {
  const [fullName, setFullName] = useState("");
  const [username, setUsername] = useState("");
  const [touched, setTouched] = useState(false);
  const [role, setRole] = useState(ROLES[4]?.slug ?? "sales"); // по умолчанию «Продажи»

  // логин автогенерится из ФИО, пока пользователь не правил поле вручную
  const login = touched ? username : makeUsername(fullName);

  function submit() {
    const u = login.trim();
    if (!fullName.trim() || !u) return;
    onAdd({ full_name: fullName.trim(), username: u, role });
    setFullName("");
    setUsername("");
    setTouched(false);
  }

  return (
    <section className="mt-5 rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
      <h2 className="text-sm font-semibold text-ink">Быстро добавить сотрудника</h2>
      <p className="mt-0.5 text-xs text-muted">
        Заводит сотрудника и сразу ставит роль (группу прав). Логин подставляется
        автоматически из ФИО.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted">ФИО</span>
          <input
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            placeholder="Иванов И.И."
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-ink outline-none focus:border-brand-600"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted">Логин</span>
          <input
            value={login}
            onChange={(e) => {
              setTouched(true);
              setUsername(e.target.value);
            }}
            placeholder="ivanov_i"
            className="rounded-lg border border-slate-200 px-3 py-2 font-mono text-sm text-ink outline-none focus:border-brand-600"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted">Роль (группа прав)</span>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-ink outline-none focus:border-brand-600"
          >
            {ROLES.map((r) => (
              <option key={r.slug} value={r.slug}>
                {r.title}
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-end">
          <button
            onClick={submit}
            disabled={!fullName.trim() || !login.trim()}
            className="w-full rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Добавить
          </button>
        </div>
      </div>
    </section>
  );
}
