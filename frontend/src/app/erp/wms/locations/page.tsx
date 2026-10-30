import { AppShell } from "@/components/app-shell";
import { WmsLocations } from "@/components/erp/wms-locations";
import { currentRole } from "@/lib/role-server";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { fetchLocationOrganizations, fetchLocationsServer } from "@/lib/wms-ops";

export default async function WmsLocationsPage() {
  const role = await currentRole();
  const auth = await backendAuthHeaders(role);
  const [locations, organizations] = await Promise.all([fetchLocationsServer(role, auth), fetchLocationOrganizations(auth)]);

  return (
    <AppShell crumbs={["ERP", "Склад", "Размещение (ячейки)"]}>
      <WmsLocations initial={locations} organizations={organizations} />
    </AppShell>
  );
}
