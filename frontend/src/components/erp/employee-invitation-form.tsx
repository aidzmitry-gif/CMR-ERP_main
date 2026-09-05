"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";

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

export interface InvitationOperation {
  operation_kind: "invite" | "activation" | string;
  request_id: number;
  employee_id: number;
  full_name: string | null;
  email: string | null;
  username: string | null;
  target_department: string;
  target_role: string;
  status: string;
  error_code: string | null;
  created_at: string;
  completed_at: string | null;
  requires_reconciliation: boolean;
}

export interface CrmStaffMember {
  employee_id: number;
  full_name: string;
  department: string;
  position?: string | null;
  email?: string | null;
  user_status?: string | null;
  role?: string | null;
  allowed_roles?: { slug: string; label: string; capabilities?: string[] }[];
}

const CRM_ROLE_OPTIONS = [
  { slug: "sales_head", label: "Продажи · РОП" },
  { slug: "sales", label: "Продажи" },
  { slug: "sales_cli", label: "Продажи · работа с клиентами" },
];

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

function errorDetail(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const detail = (body as { detail?: unknown }).detail;
  return typeof detail === "string" && detail.trim() ? detail : null;
}

function knownErrorMessage(detail: string | null, action: "invite" | "activate" | "preflight"): string {
  const messages: Record<string, string> = {
    identity_invite_reconciliation_required: "Статус приглашения требует ручной сверки в журнале операций. Повтор автоматически не выполнен.",
    identity_activation_reconciliation_required: "Статус активации требует ручной сверки в журнале операций. Повтор автоматически не выполнен.",
    identity_activation_state_drift: "Данные сотрудника изменились во время активации. Проверьте журнал операций и данные HR.",
    keycloak_invite_email_failed: "Письмо-приглашение не было подтверждено. Проверьте журнал операций перед новой попыткой.",
    keycloak_invite_transport_failed: "Сервис учётных записей временно недоступен. Письмо не отправлялось автоматически повторно.",
    keycloak_invite_redirect_uri_invalid: "Настройка ссылки возврата для приглашений требует проверки администратором.",
    keycloak_invite_lifespan_too_short: "Срок действия приглашения настроен слишком коротко. Обратитесь к администратору.",
  };
  if (detail && messages[detail]) return messages[detail];
  if (action === "preflight") return "Не удалось проверить данные приглашения. Проверьте ID, email и соответствие данным HR.";
  return action === "invite"
    ? "Не удалось подтвердить отправку приглашения. Повтор автоматически не выполнялся."
    : "Не удалось подтвердить активацию. Повтор автоматически не выполнялся.";
}

async function responseError(response: Response, action: "invite" | "activate" | "preflight"): Promise<string> {
  return knownErrorMessage(errorDetail(await response.json().catch(() => null)), action);
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
  invitationOperations = [],
  canActivate = false,
  crmStaff = [],
  crmFlow = false,
}: InvitationCatalog & {
  pendingInvitations?: PendingInvitation[];
  invitationOperations?: InvitationOperation[];
  canActivate?: boolean;
  crmStaff?: CrmStaffMember[];
  crmFlow?: boolean;
}) {
  const router = useRouter();
  const departmentNames = useMemo(() => Object.keys(departments), [departments]);
  const [employeeId, setEmployeeId] = useState("");
  const [newEmployeeName, setNewEmployeeName] = useState("");
  const [newEmployeePosition, setNewEmployeePosition] = useState("");
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
  const [locallyActivatedEmployeeIds, setLocallyActivatedEmployeeIds] = useState<Set<number>>(() => new Set());
  const idempotencyKey = useRef<string | null>(null);
  const inviteTriggerRef = useRef<HTMLButtonElement | null>(null);
  const activateTriggerRef = useRef<HTMLButtonElement | null>(null);
  const inviteConfirmRef = useRef<HTMLButtonElement | null>(null);
  const activateConfirmRef = useRef<HTMLButtonElement | null>(null);

  const roles = department ? departments[department] ?? [] : [];
  const roleOptions = crmFlow
    ? CRM_ROLE_OPTIONS
    : roles.map((name) => ({ slug: name, label: name }));
  const visiblePendingInvitations = pendingInvitations.filter(
    (item) => item.status === "onboarding" && item.role === "onboarding" && item.expected_role && !locallyActivatedEmployeeIds.has(item.employee_id),
  );

  useEffect(() => {
    if (!preflight && !activationCandidate) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || busy || activationBusy) return;
      event.preventDefault();
      if (preflight) {
        inviteTriggerRef.current?.focus();
        setPreflight(null);
      } else if (activationCandidate) {
        activateTriggerRef.current?.focus();
        setActivationCandidate(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activationBusy, activationCandidate, busy, preflight]);

  useEffect(() => {
    if (preflight) inviteConfirmRef.current?.focus();
  }, [preflight]);

  useEffect(() => {
    if (activationCandidate) activateConfirmRef.current?.focus();
  }, [activationCandidate]);

  useEffect(() => {
    if (crmFlow && !department) setDepartment("Продажи");
  }, [crmFlow, department]);

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

    let id = Number(employeeId);
    if ((!crmFlow && (!Number.isInteger(id) || id <= 0)) || !email.trim() || !department || !role) {
      setError(crmFlow
        ? "Выберите сотрудника или укажите ФИО нового сотрудника, email и роль."
        : "Заполните ID сотрудника, email, отдел и целевую рабочую роль.");
      return;
    }

    if (crmFlow && (!Number.isInteger(id) || id <= 0)) {
      if (!newEmployeeName.trim()) {
        setError("Выберите сотрудника или укажите ФИО нового сотрудника.");
        return;
      }
      setBusy(true);
      try {
        const response = await fetch("/api/system/users/crm-staff", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ full_name: newEmployeeName.trim(), ...(newEmployeePosition.trim() ? { position: newEmployeePosition.trim() } : {}) }),
        });
        if (!response.ok) {
          setError(await responseError(response, "preflight"));
          return;
        }
        const created = (await response.json()) as { employee_id?: number; id?: number };
        id = created.employee_id ?? created.id ?? 0;
        if (!Number.isInteger(id) || id <= 0) {
          setError("ERP не вернула ID созданного сотрудника. Приглашение не отправлялось.");
          return;
        }
        setEmployeeId(String(id));
        router.refresh();
      } catch {
        setError("Не удалось создать карточку сотрудника в ERP. Приглашение не отправлялось.");
        return;
      } finally {
        setBusy(false);
      }
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
        setError(await responseError(response, "preflight"));
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
          await responseError(response, "invite"),
        );
        return;
      }
      setResult((await response.json()) as InviteResult);
      setPreflight(null);
      router.refresh();
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
          await responseError(response, "activate"),
        );
        return;
      }
      setActivatedEmployeeId(activationCandidate.employee_id);
      setLocallyActivatedEmployeeIds((current) => new Set(current).add(activationCandidate.employee_id));
      setActivationCandidate(null);
      router.refresh();
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
          {crmFlow
            ? "Отдел CRM: выберите сотрудника по имени или создайте карточку, затем проверьте данные до отправки письма."
            : "Укажите ID уже созданного сотрудника из HR. Форма не показывает реестр сотрудников и сначала только проверяет выбранные данные."}
        </p>

        <section className="mt-5 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
          <b>Стартовый доступ: onboarding.</b> После регистрации сотрудник увидит только
          ознакомление с системой — без данных коллег и рабочих модулей. Целевая рабочая роль
          будет активирована отдельно ответственным руководителем.
        </section>

        {departmentNames.length === 0 && !crmFlow ? (
          <section className="mt-5 rounded-2xl border border-rose-200 bg-rose-50 p-5 text-sm text-rose-800">
            Справочник отделов недоступен. Проверьте право <code>identity.invite.prepare</code> и
            подключение к ERP.
          </section>
        ) : (
          <form onSubmit={runPreflight} aria-busy={busy} className="mt-5 rounded-2xl bg-surface p-5 shadow-card">
            <div className="grid gap-4 sm:grid-cols-2">
              {crmFlow ? (
                <>
                  <label className="flex flex-col gap-1 sm:col-span-2">
                    <span className="text-xs font-medium text-muted">Сотрудник отдела CRM</span>
                    <select
                      value={employeeId}
                      onChange={(event) => {
                        const value = event.target.value;
                        setEmployeeId(value);
                        const employee = crmStaff.find((item) => item.employee_id === Number(value));
                        if (employee?.email) setEmail(employee.email);
                        setPreflight(null);
                        setError(null);
                      }}
                      className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
                    >
                      <option value="">— новый сотрудник —</option>
                      {crmStaff.map((employee) => (
                        <option key={employee.employee_id} value={employee.employee_id}>
                          {employee.full_name}{employee.position ? ` · ${employee.position}` : ""}{employee.role ? ` · ${employee.role}` : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                  {!employeeId && (
                    <>
                      <label className="flex flex-col gap-1">
                        <span className="text-xs font-medium text-muted">ФИО нового сотрудника</span>
                        <input value={newEmployeeName} onChange={(event) => setNewEmployeeName(event.target.value)} placeholder="Иванов Иван Иванович" className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent" />
                      </label>
                      <label className="flex flex-col gap-1">
                        <span className="text-xs font-medium text-muted">Должность (необязательно)</span>
                        <input value={newEmployeePosition} onChange={(event) => setNewEmployeePosition(event.target.value)} placeholder="Менеджер по продажам" className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent" />
                      </label>
                    </>
                  )}
                </>
              ) : (
                <label className="flex flex-col gap-1">
                  <span className="text-xs font-medium text-muted">ID сотрудника из HR</span>
                  <input inputMode="numeric" value={employeeId} onChange={(event) => setEmployeeId(event.target.value)} placeholder="1350585" className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent" />
                </label>
              )}
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
              {crmFlow ? (
                <label className="flex flex-col gap-1"><span className="text-xs font-medium text-muted">Отдел</span><input value="CRM · Продажи" readOnly className="rounded-lg border border-line bg-sunken px-3 py-2 text-sm text-muted" /></label>
              ) : (
                <label className="flex flex-col gap-1">
                  <span className="text-xs font-medium text-muted">Отдел из HR</span>
                  <select value={department} onChange={(event) => changeDepartment(event.target.value)} className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent">
                    <option value="">— выберите отдел —</option>
                    {departmentNames.map((name) => (<option key={name} value={name}>{name}</option>))}
                  </select>
                </label>
              )}
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
                  {roleOptions.map((option) => (
                    <option key={option.slug} value={option.slug}>{option.label}</option>
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
                ref={inviteTriggerRef}
                className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy ? "Проверка…" : "Проверить и продолжить"}
              </button>
              <span className="text-xs text-muted">На этом шаге письмо не отправляется.</span>
            </div>
          </form>
        )}

        {error && <p role="alert" className="mt-4 text-sm text-rose-700">{error}</p>}

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
          <section aria-busy={activationBusy} className="mt-8 rounded-2xl bg-surface p-5 shadow-card">
            <h2 className="text-base font-bold text-ink">Ожидают активации</h2>
            <p className="mt-1 text-sm text-muted">
              Активация выдаёт только зафиксированные при приглашении отдел и целевую роль.
              Менять их в этой форме нельзя.
            </p>
            {visiblePendingInvitations.length === 0 ? (
              <p className="mt-4 text-sm text-muted">Нет сотрудников, ожидающих активации.</p>
            ) : (
              <ul className="mt-4 divide-y divide-line rounded-xl border border-line">
                {visiblePendingInvitations.map((item) => (
                    <li key={item.employee_id} className="flex flex-wrap items-center justify-between gap-3 p-4 text-sm">
                      <div>
                        <p className="font-medium text-ink">{item.full_name} · {item.email}</p>
                        <p className="mt-1 text-muted">План: {item.expected_department} · {item.expected_role}</p>
                      </div>
                      <button
                        type="button"
                        onClick={(event) => {
                          activateTriggerRef.current = event.currentTarget;
                          setActivationCandidate(item);
                          setActivationError(null);
                        }}
                        className="rounded-lg border border-accent px-3 py-1.5 text-xs font-semibold text-accent hover:bg-accent hover:text-white"
                      >
                        Активировать
                      </button>
                    </li>
                  ))}
              </ul>
            )}
            {activationError && <p role="alert" className="mt-3 text-sm text-rose-700">{activationError}</p>}
            {activatedEmployeeId !== null && (
              <p role="status" aria-live="polite" className="mt-3 text-sm text-emerald-700">Рабочий доступ сотрудника #{activatedEmployeeId} активирован.</p>
            )}
          </section>
        )}

        {canActivate && (
          <section className="mt-8 rounded-2xl bg-surface p-5 shadow-card">
            <h2 className="text-base font-bold text-ink">Журнал операций приглашений</h2>
            <p className="mt-1 text-sm text-muted">Только для просмотра. В журнале нет технических ключей и секретов.</p>
            {invitationOperations.length === 0 ? (
              <p className="mt-4 text-sm text-muted">Операций пока нет.</p>
            ) : (
              <ul className="mt-4 divide-y divide-line rounded-xl border border-line" aria-label="Журнал операций приглашений">
                {invitationOperations.map((operation) => (
                  <li key={`${operation.operation_kind}-${operation.request_id}`} className="p-4 text-sm">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="font-medium text-ink">{operation.operation_kind === "activation" ? "Активация" : "Приглашение"} · {operation.full_name ?? "—"}</p>
                      <span className="rounded-full bg-sunken px-2 py-0.5 text-xs text-muted">{operation.status}</span>
                    </div>
                    <p className="mt-1 text-muted">{operation.email ?? "—"} · {operation.target_department} · {operation.target_role}</p>
                    <p className="mt-1 text-xs text-muted">Создана: {new Date(operation.created_at).toLocaleString("ru-RU")}{operation.completed_at ? ` · завершена: ${new Date(operation.completed_at).toLocaleString("ru-RU")}` : ""}</p>
                    {operation.requires_reconciliation && <p role="status" className="mt-2 text-amber-800">Требуется ручная сверка статуса. Новую отправку или активацию не выполняйте автоматически.</p>}
                    {operation.error_code && <p className="mt-1 text-xs text-muted">Причина: {knownErrorMessage(operation.error_code, operation.operation_kind === "activation" ? "activate" : "invite")}</p>}
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {preflight && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4">
            <section
              role="dialog"
              aria-modal="true"
              aria-labelledby="invite-confirm-title"
              aria-describedby="invite-confirm-description"
              aria-busy={busy}
              className="w-full max-w-lg rounded-2xl bg-surface p-6 shadow-pop"
            >
              <h2 id="invite-confirm-title" className="text-lg font-bold text-ink">Подтвердите отправку</h2>
              <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
                <dt className="text-muted">Сотрудник</dt><dd className="font-medium text-ink">{preflight.full_name}</dd>
                <dt className="text-muted">Email</dt><dd className="font-medium text-ink">{preflight.email}</dd>
                <dt className="text-muted">Отдел</dt><dd className="font-medium text-ink">{preflight.department}</dd>
                <dt className="text-muted">Целевая рабочая роль</dt><dd className="font-medium text-ink">{preflight.role}</dd>
              </dl>
              <p id="invite-confirm-description" className="mt-4 rounded-xl bg-sunken p-3 text-sm text-muted">
                После регистрации будет только роль <b className="text-ink">onboarding</b>:
                ознакомление без данных коллег и рабочих модулей. Целевая роль выше включается
                отдельно.
              </p>
              <div className="mt-5 flex flex-wrap justify-end gap-3">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    inviteTriggerRef.current?.focus();
                    setPreflight(null);
                  }}
                  className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-ink hover:border-accent disabled:opacity-50"
                >
                  Отмена
                </button>
                <button
                  type="button"
                  disabled={busy}
                  ref={inviteConfirmRef}
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
            <section role="dialog" aria-modal="true" aria-labelledby="activate-confirm-title" aria-describedby="activate-confirm-description" aria-busy={activationBusy} className="w-full max-w-lg rounded-2xl bg-surface p-6 shadow-pop">
              <h2 id="activate-confirm-title" className="text-lg font-bold text-ink">Подтвердите активацию</h2>
              <p id="activate-confirm-description" className="mt-3 text-sm text-muted">
                {activationCandidate.full_name} получит рабочий доступ: <b className="text-ink">{activationCandidate.expected_department} · {activationCandidate.expected_role}</b>.
              </p>
              <p className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-950">
                Сейчас активна только роль onboarding. После подтверждения доступ к рабочим данным станет доступен согласно целевой роли.
              </p>
              <div className="mt-5 flex justify-end gap-3">
                <button type="button" disabled={activationBusy} onClick={() => { activateTriggerRef.current?.focus(); setActivationCandidate(null); }} className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-ink disabled:opacity-50">Отмена</button>
                <button type="button" disabled={activationBusy} ref={activateConfirmRef} onClick={() => void activateEmployee()} className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
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
