import { AppShell } from "@/components/app-shell";
import { ProcurementAdditionalExpenses } from "@/components/erp/procurement-additional-expenses";
import { ProcurementNav } from "@/components/erp/procurement-nav";

export default function AdditionalExpensesPage() {
  return <AppShell crumbs={["ERP", "Закупки", "Дополнительные расходы"]}><div className="flex min-w-0 flex-1 flex-col">
    <ProcurementNav /><ProcurementAdditionalExpenses />
  </div></AppShell>;
}
