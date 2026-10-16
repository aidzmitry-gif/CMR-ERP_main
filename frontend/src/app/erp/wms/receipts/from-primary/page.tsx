import { AppShell } from "@/components/app-shell";
import { WmsPrimaryReceipt } from "@/components/erp/wms-primary-receipt";

export default async function PrimaryReceiptPage({ searchParams }: { searchParams: Promise<{ org?: string; receipt?: string; version?: string }> }) {
  const params = await searchParams;
  return <AppShell crumbs={["ERP", "Склад", "Приёмка по накладной"]}><main className="min-w-0 flex-1 overflow-auto p-6"><WmsPrimaryReceipt key={JSON.stringify(params)} org={typeof params.org === "string" ? params.org : ""} receipt={typeof params.receipt === "string" ? params.receipt : ""} version={typeof params.version === "string" ? params.version : ""} /></main></AppShell>;
}
