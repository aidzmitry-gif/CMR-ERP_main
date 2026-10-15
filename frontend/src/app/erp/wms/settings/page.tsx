import { AppShell } from "@/components/app-shell";
import { WarehouseExecutionSettings } from "@/components/erp/warehouse-execution-settings";

export default function WarehouseSettingsPage() {
  return <AppShell crumbs={["ERP", "Склад", "Режим работы"]}><WarehouseExecutionSettings /></AppShell>;
}
