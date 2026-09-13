import { AppShell } from "@/components/app-shell";
import { ProcurementPostedReceipt } from "@/components/erp/procurement-posted-receipt";

export default async function PostedReceiptPage({ params, searchParams }: { params: Promise<{ entryId: string }>; searchParams: Promise<{ org?: string }> }) {
  const { entryId } = await params;
  const { org } = await searchParams;
  return <AppShell crumbs={["ERP", "Закупки", "Первичная накладная"]}>{org && /^\d+$/.test(org) && /^\d+$/.test(entryId) ? <ProcurementPostedReceipt key={`${org}/${entryId}`} org={org} entry={entryId} /> : <p className="p-6">В ссылке отсутствует корректное юрлицо или номер проводки.</p>}</AppShell>;
}
