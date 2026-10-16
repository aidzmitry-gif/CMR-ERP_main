import { AppShell } from "@/components/app-shell";
import { ProcurementKanban } from "@/components/erp/procurement-kanban";
import { ProcurementNav } from "@/components/erp/procurement-nav";

export default async function ProcurementPage({ searchParams }: { searchParams?: Promise<{ org?: string | string[] }> }) {
  const params = searchParams ? await searchParams : {};
  const suggestedOrg = typeof params.org === "string" ? params.org : undefined;
  return <AppShell crumbs={["ERP", "Закупки"]}><div className="flex min-w-0 flex-1 flex-col"><ProcurementNav /><ProcurementKanban suggestedOrg={suggestedOrg} /></div></AppShell>;
}
