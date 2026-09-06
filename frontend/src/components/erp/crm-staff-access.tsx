"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export interface CrmRoleOption {
  slug: string;
  label: string;
  capabilities?: string[];
}

export interface CrmStaffMember {
  employee_id: number;
  full_name: string;
  department: string;
  position?: string | null;
  email?: string | null;
  user_status?: string | null;
  role?: string | null;
  deal_visibility?: "all" | "own" | null;
  allowed_roles: CrmRoleOption[];
}

const VISIBILITY_OPTIONS = [
  { slug: "all" as const, label: "Все сделки CRM", description: "Видит все сделки отдела CRM" },
  { slug: "own" as const, label: "Только свои сделки", description: "Видит только назначенные ему сделки" },
];

function key(prefix: "role" | "visibility" | "employee" | "access") {
  return typeof crypto !== "undefined" && crypto.randomUUID
    ? `erp-${prefix}-${crypto.randomUUID()}`
    : `erp-${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

async function detail(response: Response, fallback: string) {
  const body = await response.json().catch(() => null) as { detail?: unknown } | null;
  return typeof body?.detail === "string" && body.detail.trim() ? body.detail : fallback;
}

async function requestFailure(response: Response, fallback: string) {
  return {
    accessDenied: response.status === 401 || response.status === 403,
    message: await detail(response, fallback),
  };
}

function roleLabel(employee: CrmStaffMember) {
  return employee.allowed_roles.find((option) => option.slug === employee.role)?.label ?? employee.role ?? "роль ещё не назначена";
}

function staffStatus(employee: CrmStaffMember) {
  if (employee.user_status === "suspended") return "доступ заблокирован";
  if (employee.user_status === "access_changing" || employee.user_status === "access_change_failed") return "изменение доступа требует сверки";
  if (employee.user_status === "onboarding") return "ознакомление";
  if (employee.user_status === "role_changing") return "смена роли: требуется сверка";
  if (employee.user_status === "role_change_failed") return "смена роли не подтверждена: требуется сверка";
  return roleLabel(employee);
}

export function CrmStaffAccess({ staff = [], loadError }: { staff?: CrmStaffMember[]; loadError?: string | null }) {
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [position, setPosition] = useState("");
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [accessError, setAccessError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [candidate, setCandidate] = useState<{ employee: CrmStaffMember; role: CrmRoleOption } | null>(null);
  const [changing, setChanging] = useState(false);
  const [visibilityCandidate, setVisibilityCandidate] = useState<{ employee: CrmStaffMember; visibility: "all" | "own" } | null>(null);
  const [changingVisibility, setChangingVisibility] = useState(false);
  const [accessCandidate, setAccessCandidate] = useState<{ employee: CrmStaffMember; enabled: boolean } | null>(null);
  const [changingAccess, setChangingAccess] = useState(false);
  const [uncertainAccess, setUncertainAccess] = useState<Set<number>>(() => new Set());

  function denyAccess(message: string) {
    setCandidate(null);
    setVisibilityCandidate(null);
    setAccessCandidate(null);
    setAccessError(message);
  }

  async function createEmployee() {
    if (!fullName.trim() || creating) return;
    setCreating(true);
    setError(null);
    try {
      const response = await fetch("/api/system/users/crm-staff", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": key("employee") },
        body: JSON.stringify({ full_name: fullName.trim(), ...(position.trim() ? { position: position.trim() } : {}) }),
      });
      if (!response.ok) {
        const failure = await requestFailure(response, "Не удалось создать карточку сотрудника.");
        if (failure.accessDenied) {
          denyAccess(failure.message);
          return;
        }
        setError(failure.message);
        return;
      }
      setFullName("");
      setPosition("");
      setMessage("Карточка сотрудника отдела CRM создана. Теперь откройте «Приглашения сотрудников» и укажите рабочий email.");
      router.refresh();
    } catch {
      setError("Результат создания карточки не подтверждён. Обновите список; повторную отправку выполняйте только после сверки.");
    } finally {
      setCreating(false);
    }
  }

  async function changeRole() {
    if (!candidate || changing) return;
    setChanging(true);
    setError(null);
    try {
      const response = await fetch(`/api/system/users/${candidate.employee.employee_id}/crm-role`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": key("role") },
        body: JSON.stringify({ role: candidate.role.slug, expected_current_role: candidate.employee.role ?? null }),
      });
      if (!response.ok) {
        const failure = await requestFailure(response, "Роль не изменена. Проверьте текущее состояние сотрудника и попробуйте снова.");
        if (failure.accessDenied) {
          denyAccess(failure.message);
          return;
        }
        setCandidate(null);
        setError(failure.message);
        return;
      }
      setMessage(`Роль «${candidate.role.label}» назначена. Доступ применится при следующем запросе сотрудника.`);
      setCandidate(null);
      router.refresh();
    } catch {
      setCandidate(null);
      setError("Результат смены роли не подтверждён. Обновите список; повторную отправку выполняйте только после сверки.");
    } finally {
      setChanging(false);
    }
  }

  async function changeVisibility() {
    if (!visibilityCandidate || changingVisibility) return;
    setChangingVisibility(true);
    setError(null);
    try {
      const response = await fetch(`/api/system/users/${visibilityCandidate.employee.employee_id}/crm-visibility`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": key("visibility") },
        body: JSON.stringify({
          deal_visibility: visibilityCandidate.visibility,
          expected_current_visibility: visibilityCandidate.employee.deal_visibility ?? "all",
        }),
      });
      if (!response.ok) {
        const failure = await requestFailure(response, "Видимость сделок не изменена. Обновите карточку сотрудника и попробуйте снова.");
        if (failure.accessDenied) {
          denyAccess(failure.message);
          return;
        }
        setVisibilityCandidate(null);
        setError(failure.message);
        return;
      }
      const label = VISIBILITY_OPTIONS.find((option) => option.slug === visibilityCandidate.visibility)?.label;
      setMessage(`Видимость сделок изменена: «${label}». При следующем запросе применяется сразу; обновите список сделок.`);
      setVisibilityCandidate(null);
      router.refresh();
    } catch {
      setVisibilityCandidate(null);
      setError("Результат изменения видимости не подтверждён. Обновите список; повторную отправку выполняйте только после сверки.");
    } finally {
      setChangingVisibility(false);
    }
  }

  async function changeAccess() {
    if (!accessCandidate || changingAccess) return;
    const { employee, enabled } = accessCandidate;
    setChangingAccess(true);
    setError(null);
    setMessage(null);
    try {
      const response = await fetch(`/api/system/users/${employee.employee_id}/crm-access`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": key("access") },
        body: JSON.stringify({ enabled, expected_current_status: employee.user_status }),
      });
      if (response.status === 401 || response.status === 403) {
        denyAccess(await detail(response, "Нет прав для изменения доступа."));
        return;
      }
      if (response.status >= 500) throw new Error("unconfirmed");
      if (!response.ok) {
        setError(await detail(response, "Состояние доступа изменилось. Обновите список перед продолжением."));
        return;
      }
      const result = await response.json() as { employee_id?: number; enabled?: boolean; status?: string };
      if (result.employee_id !== employee.employee_id || result.enabled !== enabled
        || !(enabled ? ["active", "onboarding"] : ["suspended"]).includes(result.status ?? "")) throw new Error("unconfirmed");
      setMessage(enabled ? "Прежний доступ восстановлен. Роль и видимость сделок сохранены." : "Доступ заблокирован. Рабочие запросы и новые входы запрещены.");
      router.refresh();
    } catch {
      setUncertainAccess((current) => new Set(current).add(employee.employee_id));
      setError("Результат изменения доступа не подтверждён. Нужна сверка состояния ERP и учётной записи; повтор не выполнялся.");
    } finally {
      setAccessCandidate(null);
      setChangingAccess(false);
    }
  }

  const blockingError = accessError ?? loadError;
  if (blockingError) {
    return (
      <main className="flex-1 overflow-auto bg-canvas p-6">
        <div className="mx-auto max-w-5xl">
          <h1 className="text-xl font-bold text-ink">Сотрудники отдела CRM</h1>
          <p className="mt-1 text-sm text-muted">Управление карточками, ролями и видимостью сделок доступно только после подтверждения прав сервером.</p>
          <section role="alert" className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
            <p>{blockingError}</p>
            <p className="mt-2">Управление сотрудниками скрыто, чтобы не отправить повторный запрос с неверными правами. Перейдите на <a className="underline" href="/login">вход</a> как руководитель системы, затем обновите страницу.</p>
          </section>
        </div>
      </main>
    );
  }

  return (
    <main className="flex-1 overflow-auto bg-canvas p-6">
      <div className="mx-auto max-w-5xl">
        <h1 className="text-xl font-bold text-ink">Сотрудники отдела CRM</h1>
        <p className="mt-1 text-sm text-muted">Здесь создаются карточки отдела «Продажи» и меняются только рабочие роли CRM. Приглашение и стартовый onboarding находятся на отдельном экране.</p>

        {error && <p role="alert" className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
        {message && <p role="status" className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">{message}</p>}

        <section className="mt-5 rounded-2xl bg-surface p-5 shadow-card">
          <h2 className="font-semibold text-ink">Новый сотрудник отдела CRM</h2>
          <p className="mt-1 text-sm text-muted">Создаётся только HR-карточка в отделе «Продажи». Учётная запись и письмо ещё не создаются.</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
            <label className="flex flex-col gap-1"><span className="text-xs text-muted">ФИО</span><input value={fullName} onChange={(event) => setFullName(event.target.value)} placeholder="Иванов Иван Иванович" className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent" /></label>
            <label className="flex flex-col gap-1"><span className="text-xs text-muted">Должность</span><input value={position} onChange={(event) => setPosition(event.target.value)} placeholder="Менеджер по продажам" className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent" /></label>
            <div className="flex items-end"><button type="button" disabled={creating || !fullName.trim()} onClick={() => void createEmployee()} className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50">{creating ? "Создание…" : "Создать карточку"}</button></div>
          </div>
        </section>

        <section className="mt-5 rounded-2xl bg-surface p-5 shadow-card">
          <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold text-ink">Команда CRM</h2><p className="mt-1 text-sm text-muted">После активации по умолчанию сотрудник видит все сделки отдела CRM. Роль определяет действия, а видимость — круг сделок.</p></div><a href="/erp/settings/invitations" className="rounded-lg border border-accent px-4 py-2 text-sm font-semibold text-accent hover:bg-accent hover:text-white">Пригласить сотрудника</a></div>
          {staff.length === 0 ? <p className="mt-4 text-sm text-muted">Сотрудников CRM пока нет или список недоступен.</p> : <ul className="mt-4 divide-y divide-line rounded-xl border border-line">
            {staff.map((employee) => {
              const canChangeRole = employee.user_status === "active" && Boolean(employee.role && employee.allowed_roles.some((option) => option.slug === employee.role));
              const currentVisibility = employee.deal_visibility ?? "all";
              return <li key={employee.employee_id} className="flex flex-wrap items-center justify-between gap-4 p-4 text-sm"><div><p className="font-semibold text-ink">{employee.full_name}</p><p className="mt-1 text-muted">{employee.position || "Должность не указана"} · {staffStatus(employee)}</p>{!canChangeRole && <p className="mt-1 text-xs text-muted">Рабочая роль и видимость сделок станут доступны для изменения после успешной активации и сверки.</p>}</div><div className="space-y-2"><div className="flex flex-wrap justify-end gap-2">{employee.allowed_roles.map((role) => <button key={role.slug} type="button" disabled={!canChangeRole || role.slug === employee.role} title={role.capabilities?.join(", ") || undefined} onClick={() => setCandidate({ employee, role })} className="rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-ink hover:border-accent disabled:cursor-not-allowed disabled:bg-sunken disabled:text-muted">{role.slug === employee.role ? `✓ ${role.label}` : role.label}</button>)}</div><div className="flex flex-wrap justify-end gap-2">{VISIBILITY_OPTIONS.map((option) => <button key={option.slug} type="button" disabled={!canChangeRole || option.slug === currentVisibility} title={option.description} onClick={() => setVisibilityCandidate({ employee, visibility: option.slug })} className="rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-ink hover:border-accent disabled:cursor-not-allowed disabled:bg-sunken disabled:text-muted">{option.slug === currentVisibility ? `✓ ${option.label}` : option.label}</button>)}</div>
                <div className="flex justify-end">
                  <button type="button" disabled={changingAccess || uncertainAccess.has(employee.employee_id)
                    || !["active", "onboarding", "suspended"].includes(employee.user_status ?? "")
                    || !["sales", "sales_head", "sales_cli", "onboarding"].includes(employee.role ?? "")}
                    onClick={() => setAccessCandidate({ employee, enabled: employee.user_status === "suspended" })}
                    className="rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-ink disabled:cursor-not-allowed disabled:text-muted">
                    {employee.user_status === "suspended" ? "Восстановить доступ" : "Заблокировать доступ"}
                  </button>
                </div></div></li>;
            })}
          </ul>}
        </section>

        {accessCandidate && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4">
          <section role="dialog" aria-modal="true" aria-labelledby="crm-access-title" className="w-full max-w-lg rounded-2xl bg-surface p-6 shadow-pop">
            <h2 id="crm-access-title" className="text-lg font-bold text-ink">Подтвердите изменение доступа</h2>
            <p className="mt-3 text-sm text-muted">{accessCandidate.employee.full_name}: {accessCandidate.enabled ? "восстановить прежний доступ" : "заблокировать доступ"}.</p>
            <p className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-950">
              {accessCandidate.enabled ? "Восстановятся только прежние права. Роль, пароль и видимость сделок не меняются. Ознакомительный доступ не станет рабочим." : "Рабочие запросы будут запрещены, сессии завершены, новый вход заблокирован. Карточка сотрудника и сделки сохраняются."}
            </p>
            <div className="mt-5 flex justify-end gap-3">
              <button type="button" disabled={changingAccess} onClick={() => setAccessCandidate(null)} className="rounded-lg border border-line px-4 py-2 text-sm">Отмена</button>
              <button type="button" disabled={changingAccess} onClick={() => void changeAccess()} className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white">{changingAccess ? "Изменение…" : "Подтвердить"}</button>
            </div>
          </section>
        </div>}
        {candidate && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4"><section role="dialog" aria-modal="true" aria-labelledby="crm-role-title" className="w-full max-w-lg rounded-2xl bg-surface p-6 shadow-pop"><h2 id="crm-role-title" className="text-lg font-bold text-ink">Подтвердите смену роли</h2><p className="mt-3 text-sm text-muted">{candidate.employee.full_name}: {candidate.employee.role || "роль ещё не назначена"} → <b className="text-ink">{candidate.role.label}</b>.</p><p className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-950">Сотрудник увидит изменения после обновления сессии. Доступ к сделкам отдела CRM остаётся в рамках рабочей роли.</p><div className="mt-5 flex justify-end gap-3"><button type="button" disabled={changing} onClick={() => setCandidate(null)} className="rounded-lg border border-line px-4 py-2 text-sm">Отмена</button><button type="button" disabled={changing} onClick={() => void changeRole()} className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white">{changing ? "Изменение…" : "Подтвердить"}</button></div></section></div>}
        {visibilityCandidate && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4"><section role="dialog" aria-modal="true" aria-labelledby="crm-visibility-title" className="w-full max-w-lg rounded-2xl bg-surface p-6 shadow-pop"><h2 id="crm-visibility-title" className="text-lg font-bold text-ink">Подтвердите изменение видимости сделок</h2><p className="mt-3 text-sm text-muted">{visibilityCandidate.employee.full_name}: <b className="text-ink">{VISIBILITY_OPTIONS.find((option) => option.slug === (visibilityCandidate.employee.deal_visibility ?? "all"))?.label}</b> → <b className="text-ink">{VISIBILITY_OPTIONS.find((option) => option.slug === visibilityCandidate.visibility)?.label}</b>.</p><p className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-950">Роль сотрудника не изменится. Новый круг видимых сделок применится со следующего запроса сотрудника.</p>{visibilityCandidate.visibility === "own" && <p className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">Сделки без назначенного владельца будут скрыты. В этом режиме пока недоступны лиды, сервис, Client 360, звонки и согласования.</p>}<div className="mt-5 flex justify-end gap-3"><button type="button" disabled={changingVisibility} onClick={() => setVisibilityCandidate(null)} className="rounded-lg border border-line px-4 py-2 text-sm">Отмена</button><button type="button" disabled={changingVisibility} onClick={() => void changeVisibility()} className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white">{changingVisibility ? "Изменение…" : "Подтвердить"}</button></div></section></div>}
      </div>
    </main>
  );
}
