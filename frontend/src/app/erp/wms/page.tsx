import { AppShell } from "@/components/app-shell";
import { WmsDashboard } from "@/components/erp/wms-dashboard";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { currentRole } from "@/lib/role-server";
import { fetchDashboardServer } from "@/lib/wms-warehouse";

export default async function WmsPage() {
  const role = await currentRole();
  const data = await fetchDashboardServer(role, await backendAuthHeaders(role));

  return (
    <AppShell crumbs={["ERP", "Склад"]}>
      <WmsDashboard initial={data} />
    </AppShell>
  );
}
