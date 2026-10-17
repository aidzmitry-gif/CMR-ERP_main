import { AppShell } from "@/components/app-shell";
import { SpravAdmin } from "@/components/erp/spravochniki/sprav-admin";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { fetchPendingReferenceApprovals } from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

export default async function SpravAdminPage() {
  const role = await currentRole();
  const authHeaders = await backendAuthHeaders(role);
  const pending = await fetchPendingReferenceApprovals(role, authHeaders);

  return (
    <AppShell crumbs={["ERP", "Справочники", "Модерация"]}>
      <div className="mx-auto w-full max-w-[1100px] p-6">
        <SpravAdmin initial={pending} />
      </div>
    </AppShell>
  );
}
