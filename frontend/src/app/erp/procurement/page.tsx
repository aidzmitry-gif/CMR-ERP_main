import { AppShell } from "@/components/app-shell";
import { ProcurementNav } from "@/components/erp/procurement-nav";
import { ProcurementRequestPlan } from "@/components/erp/procurement-request-plan";

export default function ProcurementPage() {
  return <AppShell crumbs={["ERP", "Закупки"]}><div className="flex min-w-0 flex-1 flex-col"><h1 className="px-6 pt-6 text-2xl font-semibold">Закупки</h1><ProcurementNav /><ProcurementRequestPlan /></div></AppShell>;
}
