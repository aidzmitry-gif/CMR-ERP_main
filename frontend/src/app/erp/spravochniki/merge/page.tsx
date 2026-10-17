import { AppShell } from "@/components/app-shell";
import { SpravMerge } from "@/components/erp/spravochniki/sprav-merge";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { fetchDuplicateClusters } from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

export default async function SpravMergePage() {
  const role = await currentRole();
  const authHeaders = await backendAuthHeaders(role);
  const clusters = await fetchDuplicateClusters(role, authHeaders);

  return (
    <AppShell crumbs={["ERP", "Справочники", "Дедупликация"]}>
      <SpravMerge initial={clusters} />
    </AppShell>
  );
}
