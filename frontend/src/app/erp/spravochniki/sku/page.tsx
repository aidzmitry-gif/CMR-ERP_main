import { AppShell } from "@/components/app-shell";
import { SpravSkuCatalog } from "@/components/erp/spravochniki/sprav-sku-catalog";
import { CATALOG_ROW_LIMIT, fetchAllSkus, fetchNomenclatureGroups, fetchVatRates } from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

export default async function SkuCatalogPage() {
  const role = await currentRole();
  const [skus, groups, vatRates] = await Promise.all([
    fetchAllSkus(role, CATALOG_ROW_LIMIT, true).then(rows => ({ rows, unavailable: false })).catch(() => ({ rows: [], unavailable: true })),
    fetchNomenclatureGroups({ roles: role }),
    fetchVatRates(undefined, role),
  ]);

  return (
    <AppShell crumbs={["ERP", "Справочники", "Номенклатура"]}>
      <SpravSkuCatalog skus={skus.rows} unavailable={skus.unavailable} groups={groups} vatRates={vatRates} />
    </AppShell>
  );
}
