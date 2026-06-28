import { AppShell } from "@/components/app-shell";
import { WmsStockTable } from "@/components/erp/wms-stock-table";
import { currentRole } from "@/lib/role-server";
import { fetchStockMirrorServer } from "@/lib/wms-stock";

export default async function WmsStockPage() {
  const role = await currentRole();
  const data = await fetchStockMirrorServer(role);

  return (
    <AppShell crumbs={["ERP", "Склад", "Остатки"]}>
      <WmsStockTable initial={data} />
    </AppShell>
  );
}
