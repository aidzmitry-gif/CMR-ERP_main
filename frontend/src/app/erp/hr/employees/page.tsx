import { AppShell } from "@/components/app-shell";
import { HrEmployeeProfiles } from "@/components/hr-employee-profiles";
import { fetchAccess } from "@/lib/access";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { currentRole } from "@/lib/role-server";

export default async function EmployeesPage() {
  const role = await currentRole();
  const access = await fetchAccess(role, await backendAuthHeaders(role));
  const canReadPrivate = Boolean(access?.current_roles.includes("hr"));
  return <AppShell crumbs={["ERP", "HR · Сотрудники"]}>
    <main className="mx-auto w-full max-w-5xl p-4 sm:p-8"><HrEmployeeProfiles canReadPrivate={canReadPrivate} /></main>
  </AppShell>;
}
