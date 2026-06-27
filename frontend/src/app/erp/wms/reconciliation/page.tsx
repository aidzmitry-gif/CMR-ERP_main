import { AppShell } from "@/components/app-shell";
import { WmsReconciliation } from "@/components/erp/wms-reconciliation";
import { currentRole } from "@/lib/role-server";
import { fetchReconServer } from "@/lib/wms-warehouse";

export default async function WmsReconciliationPage() {
  const role = await currentRole();
  const data = await fetchReconServer(role);
  return (
    <AppShell crumbs={["ERP", "Склад", "Сверка с 1С"]}>
      <WmsReconciliation initial={data} />
    </AppShell>
  );
}
