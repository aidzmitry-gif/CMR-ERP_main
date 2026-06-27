import { AppShell } from "@/components/app-shell";
import { WmsLocations } from "@/components/erp/wms-locations";
import { currentRole } from "@/lib/role-server";
import { fetchLocationsServer } from "@/lib/wms-ops";

export default async function WmsLocationsPage() {
  const role = await currentRole();
  const locations = await fetchLocationsServer(role);

  return (
    <AppShell crumbs={["ERP", "Склад", "Размещение (ячейки)"]}>
      <WmsLocations initial={locations} />
    </AppShell>
  );
}
