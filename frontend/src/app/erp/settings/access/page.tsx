import { AppShell } from "@/components/app-shell";
import { CrmStaffAccess, type CrmStaffMember } from "@/components/erp/crm-staff-access";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { currentRole } from "@/lib/role-server";

const BASE = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

async function crmStaff(role: string): Promise<{ staff: CrmStaffMember[]; error: string | null }> {
  try {
    const response = await fetch(`${BASE}/system/users/crm-staff`, { cache: "no-store", headers: await backendAuthHeaders(role) });
    if (!response.ok) return { staff: [], error: response.status === 401 || response.status === 403 ? "Недостаточно прав для управления сотрудниками CRM." : "Список сотрудников CRM временно недоступен." };
    const body = await response.json() as CrmStaffMember[];
    return { staff: Array.isArray(body) ? body : [], error: Array.isArray(body) ? null : "ERP вернула некорректные данные сотрудников." };
  } catch {
    return { staff: [], error: "Не удалось подключиться к ERP." };
  }
}

export default async function AccessAdminPage() {
  const role = await currentRole();
  const data = await crmStaff(role);
  return (
    <AppShell crumbs={["ERP", "IT и настройки", "Сотрудники CRM и роли"]}>
      <CrmStaffAccess staff={data.staff} loadError={data.error} />
    </AppShell>
  );
}
