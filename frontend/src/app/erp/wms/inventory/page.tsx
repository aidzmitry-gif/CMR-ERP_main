import { AppShell } from "@/components/app-shell";
import { WmsInventoryList } from "@/components/erp/wms-inventory-list";
import { inventoryOrganizationParam, WmsInventoryPageError } from "@/components/erp/wms-inventory-page-error";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { currentRole } from "@/lib/role-server";
import { fetchInventoryOrganizationsServer, type InventoryOrganization } from "@/lib/wms-inventory";
import { fetchInventoryListServer, type InventoryCount } from "@/lib/wms-inventory";

export default async function Page({ searchParams }: { searchParams: Promise<{ organization_id?: string }> }) {
  let data: { initial: InventoryCount[]; organizations: InventoryOrganization[] } | undefined;
  let failure: unknown;
  let organizationId: number | null = null;
  try {
    organizationId = inventoryOrganizationParam((await searchParams).organization_id);
    const role = await currentRole();
    const headers = await backendAuthHeaders(role);
    const organizations = await fetchInventoryOrganizationsServer(headers);
    const initial = organizationId === null ? [] : await fetchInventoryListServer(headers, organizationId);
    data = { initial, organizations };
  } catch (error) { failure = error; }
  if (!data) return <AppShell crumbs={["ERP", "Склад", "Инвентаризация"]}>
    <WmsInventoryPageError error={failure} href={"/erp/wms/inventory" + (organizationId === null ? "" : `?organization_id=${organizationId}`)} />
  </AppShell>;
  return <AppShell crumbs={["ERP", "Склад", "Инвентаризация"]}>
    <WmsInventoryList initial={data.initial} organizations={data.organizations} initialOrganizationId={organizationId} />
  </AppShell>;
}
