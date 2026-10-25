import { AppShell } from "@/components/app-shell";
import { ScopedWmsReconciliation } from "@/components/erp/wms-reconciliation";

export default function WmsReconciliationPage() {
  return (
    <AppShell crumbs={["ERP", "Склад", "Сверка с 1С"]}>
      <ScopedWmsReconciliation />
    </AppShell>
  );
}
