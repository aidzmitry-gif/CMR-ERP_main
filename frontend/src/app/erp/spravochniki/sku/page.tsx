import { AppShell } from "@/components/app-shell";
import { SpravSkuCatalog } from "@/components/erp/spravochniki/sprav-sku-catalog";
import { fetchAllSkus, fetchNomenclatureGroups, fetchVatRates } from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

export default async function SkuCatalogPage() {
  const role = await currentRole();
  const [skus, groups, vatRates] = await Promise.all([
    fetchAllSkus(role),
    fetchNomenclatureGroups({ roles: role }),
    fetchVatRates(undefined, role),
  ]);

  return (
    <AppShell crumbs={["ERP", "Справочники", "Номенклатура"]}>
      <SpravSkuCatalog skus={skus} groups={groups} vatRates={vatRates} />
    </AppShell>
  );
}
