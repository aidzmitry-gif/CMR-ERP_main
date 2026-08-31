import { AppShell } from "@/components/app-shell";
import {
  EmployeeInvitationForm,
  type InvitationCatalog,
  type PendingInvitation,
} from "@/components/erp/employee-invitation-form";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { currentRole } from "@/lib/role-server";

const BASE = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const SUPER_ROLES = new Set(["admin", "director", "commercial"]);

async function invitationCatalog(role: string): Promise<InvitationCatalog> {
  try {
    const response = await fetch(`${BASE}/system/users/departments`, {
      cache: "no-store",
      headers: await backendAuthHeaders(role),
    });
    if (!response.ok) return { departments: {} };
    const body = (await response.json()) as InvitationCatalog;
    if (!body.departments || typeof body.departments !== "object") return { departments: {} };
    return body;
  } catch {
    return { departments: {} };
  }
}

async function pendingInvitations(role: string): Promise<PendingInvitation[]> {
  if (!SUPER_ROLES.has(role)) return [];
  try {
    const response = await fetch(`${BASE}/system/users/invitations`, {
      cache: "no-store",
      headers: await backendAuthHeaders(role),
    });
    return response.ok ? (await response.json()) as PendingInvitation[] : [];
  } catch {
    return [];
  }
}

export default async function EmployeeInvitationsPage() {
  const role = await currentRole();
  const [catalog, invitations] = await Promise.all([invitationCatalog(role), pendingInvitations(role)]);
  return (
    <AppShell crumbs={["ERP", "IT и настройки", "Приглашения сотрудников"]}>
      <EmployeeInvitationForm
        departments={catalog.departments}
        pendingInvitations={invitations}
        canActivate={SUPER_ROLES.has(role)}
      />
    </AppShell>
  );
}
