import { AppShell } from "@/components/app-shell";
import { WmsMovements } from "@/components/erp/wms-movements";
import { currentRole } from "@/lib/role-server";
import { fetchLocationsServer, fetchMovementsServer } from "@/lib/wms-ops";

export default async function WmsMovementsPage() {
  const role = await currentRole();
  const [movements, locations] = await Promise.all([
    fetchMovementsServer(role),
    fetchLocationsServer(role),
  ]);

  return (
    <AppShell crumbs={["ERP", "Склад", "Движения и операции"]}>
      <WmsMovements initial={movements} locations={locations} />
    </AppShell>
  );
}
