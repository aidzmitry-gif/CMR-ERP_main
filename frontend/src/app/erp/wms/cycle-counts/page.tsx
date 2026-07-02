import { AppShell } from "@/components/app-shell";
import { WmsCycleCounts } from "@/components/erp/wms-cycle-counts";
import { currentRole } from "@/lib/role-server";
import { fetchCyclePlansServer } from "@/lib/wms-warehouse";

export default async function WmsCycleCountsPage() {
  const role = await currentRole();
  const plans = await fetchCyclePlansServer(role);
  const today = new Date().toISOString().slice(0, 10);
  return (
    <AppShell crumbs={["ERP", "Склад", "Цикл-каунт"]}>
      <WmsCycleCounts initial={plans} today={today} />
    </AppShell>
  );
}
