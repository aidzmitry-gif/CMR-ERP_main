import { AppShell } from "@/components/app-shell";
import { SpravSyncJournal } from "@/components/erp/spravochniki/sprav-sync-journal";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { fetchSyncJournal } from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

export default async function SpravSyncPage() {
  const role = await currentRole();
  const authHeaders = await backendAuthHeaders(role);
  const entries = await fetchSyncJournal(role, authHeaders);

  return (
    <AppShell crumbs={["ERP", "Справочники", "Синхронизация с 1С"]}>
      <SpravSyncJournal entries={entries} />
    </AppShell>
  );
}
