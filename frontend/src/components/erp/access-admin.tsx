"use client";

// Прототип «Управление доступом». Вкладки: доступ к модулям по ролям +
// системные функции (спец-права вроде удаления помеченных объектов — выдаются
// ролям и поимённо сотрудникам). Порт access-matrix.html в светлую тему приложения.
// Данные — demo (lib/access-admin-data.ts, снимок config/access.py). Записи в БД
// пока нет: кнопки «Сохранить снимок» отдают JSON для переноса на backend на шаге 2.

import { useMemo, useState } from "react";

import {
  ALL_SLUGS,
  DEFAULT_MATRIX,
  DEFAULT_SPECIAL_BY_ROLE,
  DEFAULT_SPECIAL_BY_USER,
  EMPLOYEES,
  MODULES,
  ROLES,
  SPECIAL_PERMISSIONS,
  type Employee,
  employeesByRole,
  isSuperRole,
  makeUsername,
} from "@/lib/access-admin-data";

type Matrix = Record<string, Set<string>>;

function buildMatrix(): Matrix {
  const m: Matrix = {};
  for (const r of ROLES) m[r.slug] = new Set(DEFAULT_MATRIX[r.slug] ?? []);
  return m;
}

function buildSpecialByRole(): Matrix {
  const m: Matrix = {};
  for (const r of ROLES) m[r.slug] = new Set(DEFAULT_SPECIAL_BY_ROLE[r.slug] ?? []);
  return m;
}

function buildSpecialByUser(): Matrix {
  const m: Matrix = {};
  for (const [user, perms] of Object.entries(DEFAULT_SPECIAL_BY_USER)) m[user] = new Set(perms);
  return m;
}

const TABS = [
  { key: "modules", label: "Доступ к модулям", ready: true },
  { key: "special", label: "Системные функции", ready: true },
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
      <div className="mt-5 flex flex-wrap gap-1 border-b border-line">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => t.ready && setTab(t.key)}
            disabled={!t.ready}
            className={[
              "relative -mb-px rounded-t-lg px-4 py-2 text-sm font-medium transition",
              tab === t.key
                ? "border-x border-t border-line bg-surface text-accent-ink"
                : t.ready
                  ? "text-muted hover:text-ink"
                  : "cursor-not-allowed text-faint",
            ].join(" ")}
          >
            {t.label}
            {!t.ready && (
              <span className="ml-1.5 rounded bg-sunken px-1.5 py-0.5 text-[10px] text-faint">
                скоро
              </span>
            )}
          </button>
        ))}
      </div>

      {tab === "special" ? (
        <SpecialFunctions employees={employees} flash={flash} />
      ) : tab !== "modules" ? (
        <section className="mt-6 rounded-2xl border border-dashed border-line-strong bg-surface p-10 text-center">
          <p className="text-sm text-muted">
            Этот уровень — следующий шаг. Структура заложена: после согласования экрана
            «Доступ к модулям» сюда добавим гранулярные права (например{" "}
            <code className="rounded bg-sunken px-1 text-xs">sales.deal.approve</code>),
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
            <Legend className="border-line bg-sunken">нет доступа</Legend>
            <Legend className="border-amber-400 bg-amber-50 text-amber-500">
              директор — всегда всё (заблокировано)
            </Legend>
          </div>

          <div className="mt-3 overflow-auto rounded-2xl border border-line bg-surface shadow-card">
            <table className="w-full border-separate border-spacing-0 text-[13px]">
              <thead>
                <tr>
                  <th className="sticky left-0 top-0 z-30 min-w-[230px] border-b border-r-2 border-line bg-sunken px-3 py-2 text-left font-semibold text-ink">
                    Роль / сотрудники
                  </th>
                  {MODULES.map((m) => (
                    <th
                      key={m.slug}
                      className="sticky top-0 z-20 border-b border-r border-line bg-sunken px-2 py-2 align-bottom"
                    >
                      <span className="mx-auto block h-[110px] [writing-mode:vertical-rl] rotate-180 text-xs font-medium text-muted">
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
                      <td className="sticky left-0 z-10 border-b border-r-2 border-line bg-surface px-3 py-2 align-top group-hover:bg-blue-50/40">
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
                              className="rounded border border-line px-2 py-0.5 text-[10px] text-muted hover:border-accent hover:text-ink"
                            >
                              все
                            </button>
                            <button
                              onClick={() => setRow(r.slug, false)}
                              className="rounded border border-line px-2 py-0.5 text-[10px] text-muted hover:border-accent hover:text-ink"
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
                              "border-b border-r border-line p-0 text-center align-middle",
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
                                    : "border-line bg-sunken text-transparent hover:border-accent",
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
              className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:brightness-110"
            >
              💾 Сохранить снимок
            </button>
            <button
              onClick={reset}
              className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-ink hover:border-accent"
            >
              Сбросить к предложенному
            </button>
            {toast && <span className="text-sm font-medium text-emerald-600">{toast}</span>}
          </div>

          {snapshot && (
            <section className="mt-4 rounded-2xl border border-line bg-surface p-4 shadow-card">
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-ink">
                  Снимок матрицы (JSON) — для переноса на backend
                </h2>
                <button
                  onClick={() => {
                    void navigator.clipboard.writeText(snapshot).then(() => flash("Скопировано ✓"));
                  }}
                  className="rounded-lg border border-line px-3 py-1 text-xs text-ink hover:border-accent"
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

// Экран «Системные функции» — выдача спец-прав (напр. удаление помеченных объектов)
// ролям и поимённо сотрудникам. Администраторы (супер-роли) имеют их всегда.
function SpecialFunctions({
  employees,
  flash,
}: {
  employees: Employee[];
  flash: (m: string) => void;
}) {
  const [byRoleGrants, setByRoleGrants] = useState<Matrix>(buildSpecialByRole);
  const [byUserGrants, setByUserGrants] = useState<Matrix>(buildSpecialByUser);
  const [snapshot, setSnapshot] = useState<string | null>(null);

  function toggleRole(perm: string, role: string) {
    if (isSuperRole(role)) return; // у администраторов есть всегда — не редактируем
    setByRoleGrants((prev) => {
      const next = { ...prev, [role]: new Set(prev[role]) };
      if (next[role].has(perm)) next[role].delete(perm);
      else next[role].add(perm);
      return next;
    });
  }

  function grantUser(perm: string, username: string) {
    if (!username) return;
    setByUserGrants((prev) => ({
      ...prev,
      [username]: new Set(prev[username] ?? []).add(perm),
    }));
    flash("Функция выдана сотруднику ✓");
  }

  function revokeUser(perm: string, username: string) {
    setByUserGrants((prev) => {
      const cur = new Set(prev[username] ?? []);
      cur.delete(perm);
      return { ...prev, [username]: cur };
    });
  }

  // Откуда у сотрудника функция: администратор / выдано роли / выдано лично / нет.
  function grantSource(perm: string, e: Employee): "super" | "role" | "user" | null {
    if (isSuperRole(e.role)) return "super";
    if (byRoleGrants[e.role]?.has(perm)) return "role";
    if (byUserGrants[e.username]?.has(perm)) return "user";
    return null;
  }

  function exportSnapshot() {
    const obj = Object.fromEntries(
      SPECIAL_PERMISSIONS.map((p) => [
        p.slug,
        {
          roles: ROLES.filter((r) => isSuperRole(r.slug) || byRoleGrants[r.slug]?.has(p.slug)).map(
            (r) => r.slug,
          ),
          users: employees
            .filter((e) => byUserGrants[e.username]?.has(p.slug) && !isSuperRole(e.role))
            .map((e) => e.username),
        },
      ]),
    );
    setSnapshot(JSON.stringify(obj, null, 2));
  }

  return (
    <section className="mt-6 space-y-5">
      <p className="text-sm text-muted">
        Системные функции — это право <b>выполнить операцию</b> (а не просто видеть раздел).
        Администраторы (директор / коммерческий) имеют их всегда; ниже можно выдать функцию
        ещё каким-то ролям или точечно отдельным сотрудникам.
      </p>

      {SPECIAL_PERMISSIONS.map((p) => {
        const holders = employees.filter((e) => grantSource(p.slug, e) !== null);
        const personal = employees.filter((e) => grantSource(p.slug, e) === "user");
        const candidates = employees.filter((e) => grantSource(p.slug, e) === null);
        return (
          <article
            key={p.slug}
            className={[
              "rounded-2xl border bg-surface p-5 shadow-card",
              p.danger ? "border-rose-200" : "border-line",
            ].join(" ")}
          >
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-semibold text-ink">{p.title}</h2>
              {p.danger && (
                <span className="rounded-full bg-rose-50 px-2 py-0.5 text-[11px] font-medium text-rose-600">
                  необратимо
                </span>
              )}
              <code className="rounded bg-sunken px-1.5 py-0.5 text-[11px] text-muted">
                {p.slug}
              </code>
            </div>
            <p className="mt-1 text-sm text-muted">{p.description}</p>

            {/* Роли */}
            <div className="mt-4">
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-faint">
                Кому доступно по роли
              </div>
              <div className="flex flex-wrap gap-2">
                {ROLES.map((r) => {
                  const isAdmin = isSuperRole(r.slug);
                  const on = isAdmin || byRoleGrants[r.slug]?.has(p.slug);
                  return (
                    <button
                      key={r.slug}
                      onClick={() => toggleRole(p.slug, r.slug)}
                      disabled={isAdmin}
                      title={isAdmin ? "Администратор — функция есть всегда" : undefined}
                      className={[
                        "rounded-full border px-3 py-1 text-xs font-medium transition",
                        isAdmin
                          ? "cursor-not-allowed border-amber-300 bg-amber-50 text-amber-600"
                          : on
                            ? "border-emerald-500 bg-emerald-50 text-emerald-700 hover:brightness-105"
                            : "border-line bg-sunken text-muted hover:border-accent hover:text-ink",
                      ].join(" ")}
                    >
                      {on ? "✓ " : ""}
                      {r.title}
                      {isAdmin && " · админ"}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Поимённая выдача */}
            <div className="mt-4">
              <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-faint">
                Выдать отдельному сотруднику
              </div>
              <GrantUser candidates={candidates} onGrant={(u) => grantUser(p.slug, u)} />
              {personal.length > 0 && (
                <div className="mt-2.5 flex flex-wrap gap-2">
                  {personal.map((e) => (
                    <span
                      key={e.username}
                      className="inline-flex items-center gap-1.5 rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-xs text-sky-700"
                    >
                      {e.full_name}
                      <button
                        onClick={() => revokeUser(p.slug, e.username)}
                        className="text-sky-400 hover:text-rose-600"
                        title="Забрать функцию"
                      >
                        ✕
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>

            <p className="mt-4 border-t border-line pt-3 text-xs text-muted">
              Сейчас функцию имеют: <b className="text-ink">{holders.length}</b> чел.
              {personal.length > 0 && ` (из них ${personal.length} — персонально)`}
            </p>
          </article>
        );
      })}

      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={exportSnapshot}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:brightness-110"
        >
          💾 Сохранить снимок
        </button>
      </div>

      {snapshot && (
        <section className="rounded-2xl border border-line bg-surface p-4 shadow-card">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-ink">
              Снимок системных функций (JSON) — для переноса на backend
            </h2>
            <button
              onClick={() => {
                void navigator.clipboard.writeText(snapshot).then(() => flash("Скопировано ✓"));
              }}
              className="rounded-lg border border-line px-3 py-1 text-xs text-ink hover:border-accent"
            >
              Копировать
            </button>
          </div>
          <pre className="max-h-72 overflow-auto rounded-lg bg-slate-900 p-3 text-[12px] leading-relaxed text-slate-100 thin-scroll">
            {snapshot}
          </pre>
        </section>
      )}
    </section>
  );
}

// Выбор сотрудника + «Выдать» для поимённой выдачи системной функции.
function GrantUser({
  candidates,
  onGrant,
}: {
  candidates: Employee[];
  onGrant: (username: string) => void;
}) {
  const [pick, setPick] = useState("");
  if (candidates.length === 0) {
    return <p className="text-xs text-muted">Все сотрудники уже имеют эту функцию.</p>;
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <select
        value={pick}
        onChange={(e) => setPick(e.target.value)}
        className="min-w-[220px] rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
      >
        <option value="">— выберите сотрудника —</option>
        {candidates.map((e) => (
          <option key={e.username} value={e.username}>
            {e.full_name} ({e.username})
          </option>
        ))}
      </select>
      <button
        onClick={() => {
          if (!pick) return;
          onGrant(pick);
          setPick("");
        }}
        disabled={!pick}
        className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-ink hover:border-accent disabled:cursor-not-allowed disabled:opacity-40"
      >
        Выдать
      </button>
    </div>
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
    <section className="mt-5 rounded-2xl border border-line bg-surface p-4 shadow-card">
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
            className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
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
            className="rounded-lg border border-line bg-surface px-3 py-2 font-mono text-sm text-ink outline-none focus:border-accent"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted">Роль (группа прав)</span>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
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
            className="w-full rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Добавить
          </button>
        </div>
      </div>
    </section>
  );
}
