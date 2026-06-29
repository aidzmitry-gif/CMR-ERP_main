import { AppShell } from "@/components/app-shell";
import { WmsStockView } from "@/components/erp/wms-stock-view";
import { currentRole } from "@/lib/role-server";
import { fetchStockMirrorServer } from "@/lib/wms-stock";
import { fetchThresholdsServer } from "@/lib/wms-warehouse";

export default async function WmsStockPage() {
  const role = await currentRole();
  const [data, thresholds] = await Promise.all([
    fetchStockMirrorServer(role),
    fetchThresholdsServer(role),
  ]);

  return (
    <AppShell crumbs={["ERP", "Склад", "Остатки"]}>
      <WmsStockView initial={data} thresholds={thresholds} />
    </AppShell>
  );
}
