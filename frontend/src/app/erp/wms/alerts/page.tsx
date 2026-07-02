import { AppShell } from "@/components/app-shell";
import { WmsAlerts } from "@/components/erp/wms-alerts";
import { currentRole } from "@/lib/role-server";
import { fetchAlertsServer } from "@/lib/wms-warehouse";

export default async function WmsAlertsPage() {
  const role = await currentRole();
  const data = await fetchAlertsServer(role);
  return (
    <AppShell crumbs={["ERP", "Склад", "Дефицит (low-stock)"]}>
      <WmsAlerts initial={data} />
    </AppShell>
  );
}
