import { AppShell } from "@/components/app-shell";
import { CrmStaffAccess, type CrmStaffMember } from "@/components/erp/crm-staff-access";
import { fetchAccess } from "@/lib/access";
import { resolveAppRole } from "@/lib/app-role";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { frontendAuthMode } from "@/lib/auth-mode";
import { currentRole } from "@/lib/role-server";

const BASE = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
const SUPER_ROLES = new Set(["admin", "director", "commercial"]);

type CrmManagementAccess = {
  role: string;
  headers: Record<string, string>;
  error: string | null;
};

async function crmManagementAccess(cookieRole: string): Promise<CrmManagementAccess> {
  const headers = await backendAuthHeaders(cookieRole);
  if (frontendAuthMode() !== "oidc") return { role: cookieRole, headers, error: null };

  const access = await fetchAccess(cookieRole, headers);
  if (!access || !Array.isArray(access.current_roles) || !access.current_roles.every((role) => typeof role === "string")) {
    return {
      role: "",
      headers,
      error: "Не удалось подтвердить права для управления сотрудниками CRM. Выйдите из ERP и войдите снова.",
    };
  }
  return { role: resolveAppRole(access.current_roles), headers, error: null };
}

async function crmStaff(headers: Record<string, string>): Promise<{ staff: CrmStaffMember[]; error: string | null }> {
  try {
    const response = await fetch(`${BASE}/system/users/crm-staff`, { cache: "no-store", headers });
    if (!response.ok) return { staff: [], error: response.status === 401 || response.status === 403 ? "Недостаточно прав для управления сотрудниками CRM." : "Список сотрудников CRM временно недоступен." };
    const body = await response.json() as CrmStaffMember[];
    return { staff: Array.isArray(body) ? body : [], error: Array.isArray(body) ? null : "ERP вернула некорректные данные сотрудников." };
  } catch {
    return { staff: [], error: "Не удалось подключиться к ERP." };
  }
}

export default async function AccessAdminPage() {
  const access = await crmManagementAccess(await currentRole());
  const canManage = access.error === null && SUPER_ROLES.has(access.role);
  const data = canManage
    ? await crmStaff(access.headers)
    : {
      staff: [],
      error: access.error ?? "У текущей учётной записи нет прав для управления сотрудниками CRM.",
    };
  return (
    <AppShell crumbs={["ERP", "IT и настройки", "Сотрудники CRM и роли"]}>
      <CrmStaffAccess staff={data.staff} loadError={data.error} />
    </AppShell>
  );
}
