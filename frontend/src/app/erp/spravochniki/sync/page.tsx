import { AppShell } from "@/components/app-shell";
import { SpravSyncJournal } from "@/components/erp/spravochniki/sprav-sync-journal";
import { fetchSyncJournal } from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

export default async function SpravSyncPage() {
  const role = await currentRole();
  const entries = await fetchSyncJournal(role);

  return (
    <AppShell crumbs={["ERP", "Справочники", "Синхронизация с 1С"]}>
      <SpravSyncJournal entries={entries} />
    </AppShell>
  );
}
