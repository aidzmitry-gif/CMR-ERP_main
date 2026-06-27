import { AppShell } from "@/components/app-shell";
import { WmsReceipts } from "@/components/erp/wms-receipts";
import { currentRole } from "@/lib/role-server";
import { fetchReceiptsServer } from "@/lib/wms-warehouse";

export default async function WmsReceiptsPage() {
  const role = await currentRole();
  const receipts = await fetchReceiptsServer(role);
  return (
    <AppShell crumbs={["ERP", "Склад", "Приёмка"]}>
      <WmsReceipts initial={receipts} />
    </AppShell>
  );
}
