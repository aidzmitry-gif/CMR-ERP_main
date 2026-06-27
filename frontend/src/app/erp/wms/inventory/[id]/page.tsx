import { notFound } from "next/navigation";

import { AppShell } from "@/components/app-shell";
import { WmsInventoryDetail } from "@/components/erp/wms-inventory-detail";
import { currentRole } from "@/lib/role-server";
import { fetchInventoryDetailServer } from "@/lib/wms-inventory";

export default async function WmsInventoryDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const role = await currentRole();
  const doc = await fetchInventoryDetailServer(id, role);
  if (!doc) notFound();

  return (
    <AppShell crumbs={["ERP", "Склад", "Инвентаризация", doc.number]}>
      <WmsInventoryDetail initial={doc} />
    </AppShell>
  );
}
