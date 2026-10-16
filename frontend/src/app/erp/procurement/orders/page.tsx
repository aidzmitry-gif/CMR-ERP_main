import { AppShell } from "@/components/app-shell";
import { ProcurementNav } from "@/components/erp/procurement-nav";
import { ProcurementOrderCreate } from "@/components/erp/procurement-order-create";

export default async function ProcurementOrdersPage({ searchParams }: { searchParams: Promise<{ org?: string; request?: string }> }) {
  const hints = await searchParams;
  return <AppShell crumbs={["ERP", "Закупки", "Заказы поставщикам"]}><div className="flex min-w-0 flex-1 flex-col"><ProcurementNav /><ProcurementOrderCreate suggestedOrg={hints.org} suggestedRequest={hints.request} /></div></AppShell>;
}
