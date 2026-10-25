import { AppShell } from "@/components/app-shell";
import { WmsMovements } from "@/components/erp/wms-movements";

export default function WmsMovementsPage() {
  return <AppShell crumbs={["ERP", "Склад", "Движения и операции"]}>
    <WmsMovements />
  </AppShell>;
}
