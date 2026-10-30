import { AppShell } from "@/components/app-shell";
import { WmsCycleCounts } from "@/components/erp/wms-cycle-counts";
import { inventoryOrganizationParam, WmsInventoryPageError } from "@/components/erp/wms-inventory-page-error";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { currentRole } from "@/lib/role-server";
import { fetchInstanceOrganizationServer } from "@/lib/instance-organization-server";
import { type InventoryOrganization } from "@/lib/wms-inventory";
import { fetchCyclePlansServer, type CyclePlan } from "@/lib/wms-cycle-count";

export default async function Page({ searchParams }: { searchParams: Promise<{ organization_id?: string }> }) {
  let data: { initial: CyclePlan[]; organizations: InventoryOrganization[] } | undefined;
  let failure: unknown;
  let organizationId: number | null = null;
  try {
    const hintedOrganizationId = inventoryOrganizationParam((await searchParams).organization_id);
    const role = await currentRole();
    const headers = await backendAuthHeaders(role);
    const organization = await fetchInstanceOrganizationServer(headers);
    organizationId = organization.id;
    if (hintedOrganizationId !== null && hintedOrganizationId !== organizationId) throw new Error("Юрлицо ссылки не совпадает с настройкой установки.");
    const initial = await fetchCyclePlansServer(headers, organizationId);
    data = { initial, organizations: [organization] };
  } catch (error) { failure = error; }
  if (!data) return <AppShell crumbs={["ERP", "Склад", "Цикл-каунт"]}>
    <WmsInventoryPageError error={failure} href={"/erp/wms/cycle-counts" + (organizationId === null ? "" : `?organization_id=${organizationId}`)} />
  </AppShell>;
  return <AppShell crumbs={["ERP", "Склад", "Цикл-каунт"]}>
    <WmsCycleCounts initial={data.initial} organizations={data.organizations} initialOrganizationId={organizationId} today={new Date().toISOString().slice(0, 10)} />
  </AppShell>;
}
