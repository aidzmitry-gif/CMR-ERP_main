import { AppShell } from "@/components/app-shell";
import { ProcurementAdditionalExpenses } from "@/components/erp/procurement-additional-expenses";

export default function AdditionalExpensesPage() {
  return <AppShell crumbs={["ERP", "Закупки", "Дополнительные расходы"]}><div className="flex min-w-0 flex-1 flex-col">
    <ProcurementAdditionalExpenses />
  </div></AppShell>;
}
