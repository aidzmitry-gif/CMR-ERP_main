import { AppShell } from "@/components/app-shell";
import { NormsTable } from "@/components/erp/norms-table";
import { fetchNormsServer } from "@/lib/production-norms";
import { currentRole } from "@/lib/role-server";

export default async function ProductionNormsPage() {
  const role = await currentRole();
  const norms = await fetchNormsServer(role);

  return (
    <AppShell crumbs={["ERP", "Производство", "Нормы и нормативы"]}>
      <NormsTable initial={norms} />
    </AppShell>
  );
}
