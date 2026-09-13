import { AppShell } from "@/components/app-shell";
import { ProcurementNav } from "@/components/erp/procurement-nav";
import { ProcurementRequestPlan } from "@/components/erp/procurement-request-plan";

export default function ProcurementPage() {
  return <AppShell crumbs={["ERP", "Закупки"]}><div className="flex min-w-0 flex-1 flex-col"><ProcurementNav /><ProcurementRequestPlan /></div></AppShell>;
}
