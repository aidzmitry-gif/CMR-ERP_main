"use client";

import { type FormEvent, useMemo, useRef, useState } from "react";

export interface InvitationCatalog {
  departments: Record<string, string[]>;
}

export interface PendingInvitation {
  employee_id: number;
  full_name: string;
  email: string;
  status: string;
  role: string;
  expected_department: string;
  expected_role: string;
}

interface InvitePayload {
  employee_id: number;
  email: string;
  department: string;
  role: string;
  username?: string;
}

interface Preflight extends InvitePayload {
  full_name: string;
  username: string;
  ready: boolean;
}

interface InviteResult {
  full_name: string;
  username: string;
  email: string;
  department: string;
  role: string;
  expected_department: string;
  expected_role: string;
  status: string;
}

function errorDetail(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const detail = (body as { detail?: unknown }).detail;
  return typeof detail === "string" && detail.trim() ? detail : fallback;
}

async function responseError(response: Response, fallback: string): Promise<string> {
  return errorDetail(await response.json().catch(() => null), fallback);
}

function newIdempotencyKey(prefix: "invite" | "activate"): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `erp-${prefix}-${crypto.randomUUID()}`;
  }
  // Fallback only for old browsers: safe characters and length satisfy backend validation.
  return `erp-${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

/**
 * Закрытая форма. Она не читает список сотрудников: оператор вручную вводит ID
 * из HR и сначала получает только preflight конкретного сотрудника.
 */
export function EmployeeInvitationForm({
  departments,
  pendingInvitations = [],
  canActivate = false,
}: InvitationCatalog & { pendingInvitations?: PendingInvitation[]; canActivate?: boolean }) {
  const departmentNames = useMemo(() => Object.keys(departments), [departments]);
  const [employeeId, setEmployeeId] = useState("");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [department, setDepartment] = useState("");
  const [role, setRole] = useState("");
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<InviteResult | null>(null);
  const [activationCandidate, setActivationCandidate] = useState<PendingInvitation | null>(null);
  const [activationBusy, setActivationBusy] = useState(false);
  const [activationError, setActivationError] = useState<string | null>(null);
  const [activatedEmployeeId, setActivatedEmployeeId] = useState<number | null>(null);
  const idempotencyKey = useRef<string | null>(null);

  const roles = department ? departments[department] ?? [] : [];

  function changeDepartment(nextDepartment: string) {
    setDepartment(nextDepartment);
    setRole("");
    setPreflight(null);
    setError(null);
  }

  function clearResult() {
    setResult(null);
    setPreflight(null);
    idempotencyKey.current = null;
    setError(null);
  }

  async function runPreflight(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    clearResult();

    const id = Number(employeeId);
    if (!Number.isInteger(id) || id <= 0 || !email.trim() || !department || !role) {
      setError("Заполните ID сотрудника, email, отдел и целевую рабочую роль.");
      return;
    }
    const payload: InvitePayload = {
      employee_id: id,
      email: email.trim(),
      department,
      role,
      ...(username.trim() ? { username: username.trim() } : {}),
    };

    setBusy(true);
    try {
      const response = await fetch("/api/system/users/preflight", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        setError(await responseError(response, "Не удалось проверить данные приглашения."));
        return;
      }
      const checked = (await response.json()) as Preflight;
      if (!checked.ready) {
        setError("Сотрудник уже связан с учётной записью. Новое письмо не будет отправлено.");
        return;
      }
      setPreflight(checked);
    } catch {
      setError("Не удалось связаться с ERP. Письмо не отправлялось.");
    } finally {
      setBusy(false);
    }
  }

  async function sendInvitation() {
    if (!preflight || busy) return;
    setBusy(true);
    setError(null);
    idempotencyKey.current ??= newIdempotencyKey("invite");
    const payload: InvitePayload = {
      employee_id: preflight.employee_id,
      email: preflight.email,
      department: preflight.department,
      role: preflight.role,
      username: preflight.username,
    };
    try {
      const response = await fetch("/api/system/users/invite", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey.current,
        },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        setPreflight(null);
        setError(
          `${await responseError(response, "Статус отправки требует ручной сверки.")} Повтор автоматически не выполнялся.`,
        );
        return;
      }
      setResult((await response.json()) as InviteResult);
      setPreflight(null);
    } catch {
      // Не делаем retry: внешний эффект мог уже начаться, а ключ остаётся в журнале backend.
      setPreflight(null);
      setError("Статус отправки неизвестен. Повтор не выполнен: проверьте журнал приглашений у администратора.");
    } finally {
      setBusy(false);
    }
  }

  async function activateEmployee() {
    if (!activationCandidate || activationBusy) return;
    setActivationBusy(true);
    setActivationError(null);
    const key = newIdempotencyKey("activate");
    try {
      const response = await fetch(`/api/system/users/${activationCandidate.employee_id}/activate`, {
        method: "POST",
        headers: { "Idempotency-Key": key },
      });
      if (!response.ok) {
        setActivationCandidate(null);
        setActivationError(
          `${await responseError(response, "Активация требует ручной сверки.")} Повтор автоматически не выполнялся.`,
        );
        return;
      }
      setActivatedEmployeeId(activationCandidate.employee_id);
      setActivationCandidate(null);
    } catch {
      setActivationCandidate(null);
      setActivationError("Статус активации неизвестен. Повтор не выполнен: проверьте журнал приглашений.");
    } finally {
      setActivationBusy(false);
    }
  }

  return (
    <main className="flex-1 overflow-auto bg-canvas p-6">
      <div className="mx-auto max-w-3xl">
        <h1 className="text-xl font-bold text-ink">Пригласить сотрудника</h1>
        <p className="mt-1 text-sm text-muted">
          Укажите ID уже созданного сотрудника из HR. Форма не показывает реестр сотрудников и
          сначала только проверяет выбранные данные.
        </p>

        <section className="mt-5 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
          <b>Стартовый доступ: onboarding.</b> После регистрации сотрудник увидит только
          ознакомление с системой — без данных коллег и рабочих модулей. Целевая рабочая роль
          будет активирована отдельно ответственным руководителем.
        </section>

        {departmentNames.length === 0 ? (
          <section className="mt-5 rounded-2xl border border-rose-200 bg-rose-50 p-5 text-sm text-rose-800">
            Справочник отделов недоступен. Проверьте право <code>identity.invite.prepare</code> и
            подключение к ERP.
          </section>
        ) : (
          <form onSubmit={runPreflight} className="mt-5 rounded-2xl bg-surface p-5 shadow-card">
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-muted">ID сотрудника из HR</span>
                <input
                  inputMode="numeric"
                  value={employeeId}
                  onChange={(event) => setEmployeeId(event.target.value)}
                  placeholder="1350585"
                  className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-muted">Рабочий email</span>
                <input
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="name@microchips.by"
                  className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-muted">Отдел из HR</span>
                <select
                  value={department}
                  onChange={(event) => changeDepartment(event.target.value)}
                  className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
                >
                  <option value="">— выберите отдел —</option>
                  {departmentNames.map((name) => (
                    <option key={name} value={name}>{name}</option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs font-medium text-muted">Целевая рабочая роль</span>
                <select
                  value={role}
                  disabled={!department}
                  onChange={(event) => {
                    setRole(event.target.value);
                    setPreflight(null);
                    setError(null);
                  }}
                  className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <option value="">— выберите роль —</option>
                  {roles.map((name) => (
                    <option key={name} value={name}>{name}</option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 sm:col-span-2">
                <span className="text-xs font-medium text-muted">Логин (необязательно)</span>
                <input
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder="Будет сформирован из email, если оставить пустым"
                  className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
                />
              </label>
            </div>

            <div className="mt-5 flex flex-wrap items-center gap-3">
              <button
                type="submit"
                disabled={busy}
                className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy ? "Проверка…" : "Проверить и продолжить"}
              </button>
              <span className="text-xs text-muted">На этом шаге письмо не отправляется.</span>
            </div>
          </form>
        )}

        <p aria-live="polite" className="mt-4 text-sm text-rose-700">{error}</p>

        {result && (
          <section className="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 p-5 text-sm text-emerald-900">
            <h2 className="font-semibold">Приглашение отправлено</h2>
            <p className="mt-1">
              {result.full_name} · {result.email} · целевой отдел и роль: <b>{result.expected_department} · {result.expected_role}</b>.
              Стартовая роль остаётся <b>onboarding</b> до отдельной активации.
            </p>
            <button
              type="button"
              onClick={clearResult}
              className="mt-3 rounded-lg border border-emerald-300 px-3 py-1.5 text-xs font-medium hover:bg-emerald-100"
            >
              Новое приглашение
            </button>
          </section>
        )}

        {canActivate && (
          <section className="mt-8 rounded-2xl bg-surface p-5 shadow-card">
            <h2 className="text-base font-bold text-ink">Ожидают активации</h2>
            <p className="mt-1 text-sm text-muted">
              Активация выдаёт только зафиксированные при приглашении отдел и целевую роль.
              Менять их в этой форме нельзя.
            </p>
            {pendingInvitations.filter((item) => item.status === "onboarding" && item.role === "onboarding" && item.expected_role).length === 0 ? (
              <p className="mt-4 text-sm text-muted">Нет сотрудников, ожидающих активации.</p>
            ) : (
              <ul className="mt-4 divide-y divide-line rounded-xl border border-line">
                {pendingInvitations
                  .filter((item) => item.status === "onboarding" && item.role === "onboarding" && item.expected_role)
                  .map((item) => (
                    <li key={item.employee_id} className="flex flex-wrap items-center justify-between gap-3 p-4 text-sm">
                      <div>
                        <p className="font-medium text-ink">{item.full_name} · {item.email}</p>
                        <p className="mt-1 text-muted">План: {item.expected_department} · {item.expected_role}</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => { setActivationCandidate(item); setActivationError(null); }}
                        className="rounded-lg border border-accent px-3 py-1.5 text-xs font-semibold text-accent hover:bg-accent hover:text-white"
                      >
                        Активировать
                      </button>
                    </li>
                  ))}
              </ul>
            )}
            <p aria-live="polite" className="mt-3 text-sm text-rose-700">{activationError}</p>
            {activatedEmployeeId !== null && (
              <p className="mt-3 text-sm text-emerald-700">Рабочий доступ сотрудника #{activatedEmployeeId} активирован.</p>
            )}
          </section>
        )}

        {preflight && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4">
            <section
              role="dialog"
              aria-modal="true"
              aria-labelledby="invite-confirm-title"
              className="w-full max-w-lg rounded-2xl bg-surface p-6 shadow-pop"
            >
              <h2 id="invite-confirm-title" className="text-lg font-bold text-ink">Подтвердите отправку</h2>
              <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
                <dt className="text-muted">Сотрудник</dt><dd className="font-medium text-ink">{preflight.full_name}</dd>
                <dt className="text-muted">Email</dt><dd className="font-medium text-ink">{preflight.email}</dd>
                <dt className="text-muted">Отдел</dt><dd className="font-medium text-ink">{preflight.department}</dd>
                <dt className="text-muted">Целевая рабочая роль</dt><dd className="font-medium text-ink">{preflight.role}</dd>
              </dl>
              <p className="mt-4 rounded-xl bg-sunken p-3 text-sm text-muted">
                После регистрации будет только роль <b className="text-ink">onboarding</b>:
                ознакомление без данных коллег и рабочих модулей. Целевая роль выше включается
                отдельно.
              </p>
              <div className="mt-5 flex flex-wrap justify-end gap-3">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setPreflight(null)}
                  className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-ink hover:border-accent disabled:opacity-50"
                >
                  Отмена
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void sendInvitation()}
                  className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
                >
                  {busy ? "Отправка…" : "Отправить приглашение"}
                </button>
              </div>
            </section>
          </div>
        )}

        {activationCandidate && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4">
            <section role="dialog" aria-modal="true" aria-labelledby="activate-confirm-title" className="w-full max-w-lg rounded-2xl bg-surface p-6 shadow-pop">
              <h2 id="activate-confirm-title" className="text-lg font-bold text-ink">Подтвердите активацию</h2>
              <p className="mt-3 text-sm text-muted">
                {activationCandidate.full_name} получит рабочий доступ: <b className="text-ink">{activationCandidate.expected_department} · {activationCandidate.expected_role}</b>.
              </p>
              <p className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-950">
                Сейчас активна только роль onboarding. После подтверждения доступ к рабочим данным станет доступен согласно целевой роли.
              </p>
              <div className="mt-5 flex justify-end gap-3">
                <button type="button" disabled={activationBusy} onClick={() => setActivationCandidate(null)} className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-ink disabled:opacity-50">Отмена</button>
                <button type="button" disabled={activationBusy} onClick={() => void activateEmployee()} className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
                  {activationBusy ? "Активация…" : "Подтвердить активацию"}
                </button>
              </div>
            </section>
          </div>
        )}
      </div>
    </main>
  );
}
