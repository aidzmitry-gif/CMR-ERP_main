import { AppShell } from "@/components/app-shell";
import { WmsCycleCounts } from "@/components/erp/wms-cycle-counts";
import { inventoryOrganizationParam, WmsInventoryPageError } from "@/components/erp/wms-inventory-page-error";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { currentRole } from "@/lib/role-server";
import { fetchInventoryOrganizationsServer, type InventoryOrganization } from "@/lib/wms-inventory";
import { fetchCyclePlansServer, type CyclePlan } from "@/lib/wms-cycle-count";

export default async function Page({ searchParams }: { searchParams: Promise<{ organization_id?: string }> }) {
  let data: { initial: CyclePlan[]; organizations: InventoryOrganization[] } | undefined;
  let failure: unknown;
  let organizationId: number | null = null;
  try {
    organizationId = inventoryOrganizationParam((await searchParams).organization_id);
    const role = await currentRole();
    const headers = await backendAuthHeaders(role);
    const organizations = await fetchInventoryOrganizationsServer(headers);
    const initial = organizationId === null ? [] : await fetchCyclePlansServer(headers, organizationId);
    data = { initial, organizations };
  } catch (error) { failure = error; }
  if (!data) return <AppShell crumbs={["ERP", "Склад", "Цикл-каунт"]}>
    <WmsInventoryPageError error={failure} href={"/erp/wms/cycle-counts" + (organizationId === null ? "" : `?organization_id=${organizationId}`)} />
  </AppShell>;
  return <AppShell crumbs={["ERP", "Склад", "Цикл-каунт"]}>
    <WmsCycleCounts initial={data.initial} organizations={data.organizations} initialOrganizationId={organizationId} today={new Date().toISOString().slice(0, 10)} />
  </AppShell>;
}
