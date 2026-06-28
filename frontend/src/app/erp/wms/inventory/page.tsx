import { AppShell } from "@/components/app-shell";
import { WmsInventoryList } from "@/components/erp/wms-inventory-list";
import { currentRole } from "@/lib/role-server";
import { fetchInventoryListServer } from "@/lib/wms-inventory";

export default async function WmsInventoryPage() {
  const role = await currentRole();
  const docs = await fetchInventoryListServer(role);

  return (
    <AppShell crumbs={["ERP", "Склад", "Инвентаризация"]}>
      <WmsInventoryList initial={docs} />
    </AppShell>
  );
}
