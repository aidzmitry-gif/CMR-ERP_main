import { notFound } from "next/navigation";

import { AppShell } from "@/components/app-shell";
import { WmsReceiptDetail } from "@/components/erp/wms-receipt-detail";
import { currentRole } from "@/lib/role-server";
import { fetchReceiptServer } from "@/lib/wms-warehouse";

export default async function WmsReceiptDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const role = await currentRole();
  const doc = await fetchReceiptServer(id, role);
  if (!doc) notFound();
  return (
    <AppShell crumbs={["ERP", "Склад", "Приёмка", doc.number]}>
      <WmsReceiptDetail initial={doc} />
    </AppShell>
  );
}
