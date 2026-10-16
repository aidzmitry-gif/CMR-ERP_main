import { AppShell } from "@/components/app-shell";
import { ProcurementNav } from "@/components/erp/procurement-nav";
import { ProcurementRequestPlan } from "@/components/erp/procurement-request-plan";

export default async function ProcurementPlanningPage({ searchParams }: { searchParams?: Promise<{ org?: string | string[] }> }) {
  const params = searchParams ? await searchParams : {};
  const suggestedOrg = typeof params.org === "string" ? params.org : undefined;
  return <AppShell crumbs={["ERP", "Закупки", "План закупок"]}><div className="flex min-w-0 flex-1 flex-col"><ProcurementNav /><ProcurementRequestPlan suggestedOrg={suggestedOrg} /></div></AppShell>;
}
