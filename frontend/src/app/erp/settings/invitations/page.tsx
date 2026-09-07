import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import {
  EmployeeInvitationForm,
  type CrmStaffMember,
  type InvitationCatalog,
  type InvitationOperation,
  type PendingInvitation,
} from "@/components/erp/employee-invitation-form";
import { fetchAccess } from "@/lib/access";
import { resolveAppRole } from "@/lib/app-role";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { frontendAuthMode } from "@/lib/auth-mode";
import { currentRole } from "@/lib/role-server";

const BASE = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const SUPER_ROLES = new Set(["admin", "director", "commercial"]);

type InvitationAccess = {
  role: string;
  headers: Record<string, string>;
  error: string | null;
};

async function invitationAccess(cookieRole: string): Promise<InvitationAccess> {
  const headers = await backendAuthHeaders(cookieRole);
  if (frontendAuthMode() !== "oidc") return { role: cookieRole, headers, error: null };

  const access = await fetchAccess(cookieRole, headers);
  if (!access || !Array.isArray(access.current_roles) || !access.current_roles.every((role) => typeof role === "string")) {
    return {
      role: "",
      headers,
      error: "Не удалось подтвердить права для приглашений. Войдите в ERP заново и повторите попытку.",
    };
  }
  return { role: resolveAppRole(access.current_roles), headers, error: null };
}

type InvitationRead<T> = { data: T | null; error: string | null };

async function invitationRead<T>(
  path: string,
  label: string,
  headers: Record<string, string>,
  valid: (body: unknown) => body is T,
): Promise<InvitationRead<T>> {
  try {
    const response = await fetch(`${BASE}/system/users/${path}`, {
      cache: "no-store",
      headers,
    });
    if (!response.ok) return {
      data: null,
      error: response.status === 401 || response.status === 403
        ? `Нет доступа: ${label}. Войдите заново и обновите страницу.`
        : `Не удалось загрузить ${label}. Обновите страницу перед продолжением.`,
    };
    const body: unknown = await response.json();
    return valid(body)
      ? { data: body, error: null }
      : { data: null, error: `ERP вернула некорректные данные: ${label}.` };
  } catch {
    return { data: null, error: `Не удалось загрузить ${label}. Проверьте соединение и обновите страницу.` };
  }
}

function isCatalog(body: unknown): body is InvitationCatalog {
  if (!body || typeof body !== "object" || !("departments" in body)) return false;
  const departments = body.departments;
  return departments !== null && typeof departments === "object" && !Array.isArray(departments)
    && Object.values(departments).every((roles) => Array.isArray(roles) && roles.every((role) => typeof role === "string"));
}

function isRecordList<T>(body: unknown): body is T[] {
  return Array.isArray(body) && body.every((item) => item !== null && typeof item === "object" && !Array.isArray(item));
}

async function crmStaff(headers: Record<string, string>, generalFlow = false): Promise<{ staff: CrmStaffMember[]; error: string | null }> {
  try {
    const response = await fetch(`${BASE}${generalFlow ? "/hr/employees" : "/system/users/crm-staff"}`, { cache: "no-store", headers });
    if (!response.ok) {
      return {
        staff: [],
        error: response.status === 401 || response.status === 403
          ? "У текущей учётной записи нет прав для просмотра сотрудников выбранного раздела."
          : "Список сотрудников временно недоступен.",
      };
    }
    const body = await response.json();
    if (generalFlow) {
      if (!Array.isArray(body) || !body.every((item) => item && Number.isInteger(item.id) && item.id > 0
        && typeof item.full_name === "string" && typeof item.department === "string"
        && typeof item.position === "string" && typeof item.status === "string")) {
        return { staff: [], error: "ERP вернула некорректные данные сотрудников." };
      }
      return { staff: body.filter((item) => item.status === "active").map((item) => ({
        employee_id: item.id, full_name: item.full_name, department: item.department, position: item.position,
      })), error: null };
    }
    return Array.isArray(body)
      ? { staff: body, error: null }
      : { staff: [], error: "ERP вернула некорректные данные сотрудников." };
  } catch {
    return { staff: [], error: "Не удалось подключиться к ERP." };
  }
}

export default async function EmployeeInvitationsPage({ searchParams }: {
  searchParams?: Promise<{ scope?: string | string[] }>;
}) {
  const access = await invitationAccess(await currentRole());
  const generalFlow = (await searchParams)?.scope === "erp";
  const canActivate = access.error === null && SUPER_ROLES.has(access.role);
  const canPrepare = canActivate || (!generalFlow && access.error === null && access.role === "crm_invitation_operator");
  const accessError = access.error ?? (canPrepare ? null : generalFlow
    ? "Приглашения в другие отделы доступны только руководителю."
    : "Подготовка приглашений требует полномочий руководителя или отдельно назначенного оператора CRM.");
  const [catalog, invitations, operations, staff] = canPrepare
    ? await Promise.all([
      invitationRead("departments", "справочник отделов и ролей", access.headers, isCatalog),
      invitationRead("invitations", "список ожидающих активации", access.headers, isRecordList<PendingInvitation>),
      invitationRead("invitation-operations", "журнал операций приглашений", access.headers, isRecordList<InvitationOperation>),
      crmStaff(access.headers, generalFlow),
    ])
    : [{ data: null, error: null }, { data: null, error: null }, { data: null, error: null }, { staff: [], error: null }];
  return (
    <AppShell crumbs={["ERP", "IT и настройки", "Приглашения сотрудников"]}>
      <div className="flex min-w-0 flex-1 flex-col">
      {canActivate && (
        <nav aria-label="Раздел приглашений" className="flex flex-wrap gap-4 border-b border-line bg-surface px-6 py-3 text-sm">
          <Link href="/erp/settings/invitations" aria-current={!generalFlow ? "page" : undefined} className="text-accent">Сотрудники CRM</Link>
          <Link href="/erp/settings/invitations?scope=erp" aria-current={generalFlow ? "page" : undefined} className="text-accent">Руководители и другие отделы</Link>
        </nav>
      )}
      <EmployeeInvitationForm
        key={generalFlow ? "erp" : "crm"}
        departments={catalog.data?.departments ?? {}}
        pendingInvitations={invitations.data ?? []}
        invitationOperations={operations.data ?? []}
        canActivate={canActivate}
        canReadOperations={canPrepare}
        crmStaff={staff.staff}
        crmFlow={canPrepare && !generalFlow}
        generalFlow={canPrepare && generalFlow}
        accessError={accessError ?? staff.error ?? catalog.error ?? invitations.error ?? operations.error}
      />
      </div>
    </AppShell>
  );
}
