import { notFound } from "next/navigation";
import { AppShell } from "@/components/app-shell";
import { WmsInventoryDetail } from "@/components/erp/wms-inventory-detail";
import { WmsInventoryPageError } from "@/components/erp/wms-inventory-page-error";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { currentRole } from "@/lib/role-server";
import { fetchInventoryDetailServer, type InventoryDetail, InventoryRequestError } from "@/lib/wms-inventory";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let doc: InventoryDetail | undefined;
  let failure: unknown;
  try {
    const role = await currentRole();
    doc = await fetchInventoryDetailServer(id, await backendAuthHeaders(role));
  } catch (error) { failure = error; }
  if (!doc) {
    if (failure instanceof InventoryRequestError && failure.status === 404) notFound();
    return <AppShell crumbs={["ERP", "Склад", "Инвентаризация"]}><WmsInventoryPageError error={failure} href={`/erp/wms/inventory/${encodeURIComponent(id)}`} /></AppShell>;
  }
  return <AppShell crumbs={["ERP", "Склад", "Инвентаризация", doc.number]}><WmsInventoryDetail initial={doc} /></AppShell>;
}
