import { AppShell } from "@/components/app-shell";
import { ProcurementCostCalc } from "@/components/erp/procurement-cost-calc";
import { ProcurementNav } from "@/components/erp/procurement-nav";

export default function ProcurementCostCalcPage() {
  return (
    <AppShell crumbs={["ERP", "Закупки", "Калькулятор себестоимости"]}>
      <div className="flex min-w-0 flex-1 flex-col">
        <ProcurementNav />
        <ProcurementCostCalc />
      </div>
    </AppShell>
  );
}
