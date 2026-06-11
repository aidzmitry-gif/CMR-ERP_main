import { AppShell } from "@/components/app-shell";
import { BomPanel } from "@/components/erp/bom-panel";
import { fetchBomsServer } from "@/lib/production-bom";
import { currentRole } from "@/lib/role-server";

export default async function ProductionBomPage() {
  const role = await currentRole();
  const boms = await fetchBomsServer(role);

  return (
    <AppShell crumbs={["ERP", "Производство", "Спецификации · BOM"]}>
      <BomPanel initial={boms} />
    </AppShell>
  );
}
