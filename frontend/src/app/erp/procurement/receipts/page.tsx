import { AppShell } from "@/components/app-shell";
import { ProcurementNav } from "@/components/erp/procurement-nav";
import { ProcurementReceipts } from "@/components/erp/procurement-receipts";

export default async function ProcurementReceiptsPage({ searchParams }: { searchParams: Promise<{ org?: string | string[]; receipt?: string | string[] }> }) {
  const params = await searchParams;
  return <AppShell crumbs={["ERP", "Закупки", "Накладные на поступление"]}><div className="flex min-w-0 flex-1 flex-col"><ProcurementNav /><div className="flex min-h-0 flex-1"><ProcurementReceipts key={JSON.stringify([params.org, params.receipt])} initialOrganization={Array.isArray(params.org) ? "" : params.org} initialReceipt={Array.isArray(params.receipt) ? "" : params.receipt} /></div></div></AppShell>;
}
