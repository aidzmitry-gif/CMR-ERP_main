import { AppShell } from "@/components/app-shell";
import { WmsReceiptReconciliation } from "@/components/erp/wms-receipt-reconciliation";

export default function ReceiptReconciliationPage() {
  return <AppShell crumbs={["ERP", "Склад", "Сопоставление приёмок"]}><WmsReceiptReconciliation /></AppShell>;
}
