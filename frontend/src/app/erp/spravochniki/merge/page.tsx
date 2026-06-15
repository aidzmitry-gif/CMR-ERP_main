import { AppShell } from "@/components/app-shell";
import { SpravMerge } from "@/components/erp/spravochniki/sprav-merge";
import { fetchDuplicateClusters } from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

export default async function SpravMergePage() {
  const role = await currentRole();
  const clusters = await fetchDuplicateClusters(role);

  return (
    <AppShell crumbs={["ERP", "Справочники", "Дедупликация"]}>
      <SpravMerge initial={clusters} />
    </AppShell>
  );
}
