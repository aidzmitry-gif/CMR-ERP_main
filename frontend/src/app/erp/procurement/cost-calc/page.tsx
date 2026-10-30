import { AppShell } from "@/components/app-shell";
import { ProcurementCostCalc } from "@/components/erp/procurement-cost-calc";

export default function ProcurementCostCalcPage() {
  return (
    <AppShell crumbs={["ERP", "Закупки", "Калькулятор себестоимости"]}>
      <main className="min-w-0 w-0 flex-1 overflow-auto p-4 sm:p-6 lg:pr-12">
        <ProcurementCostCalc />
      </main>
    </AppShell>
  );
}
