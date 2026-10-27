import { AppShell } from "@/components/app-shell";
import { WmsOperationHistory } from "@/components/erp/wms-operation-history";

export default function WmsOperationsPage() {
  return <AppShell crumbs={["ERP", "Склад", "История операций"]}><WmsOperationHistory /></AppShell>;
}
