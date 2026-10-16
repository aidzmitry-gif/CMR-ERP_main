import { notFound } from "next/navigation";
import { AppShell } from "@/components/app-shell";
import { ProcurementMachineEditor } from "@/components/erp/procurement-machine-editor";

export default async function ProcurementOrderEditorPage({ params, searchParams }: {
  params: Promise<{ id: string }>; searchParams: Promise<{ org?: string }>;
}) {
  const { id } = await params; const { org } = await searchParams;
  if (!/^[1-9]\d*$/.test(id) || Number(id) > 2147483647) notFound();
  return <AppShell crumbs={["ERP", "Закупки", "Заказ"]}><ProcurementMachineEditor orderId={Number(id)} suggestedOrg={org} /></AppShell>;
}
