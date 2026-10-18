import { AppShell } from "@/components/app-shell";
import { SkuCatalogContent, type SkuCatalogSearchParams } from "@/components/erp/spravochniki/sprav-sku-catalog";

export default async function SkuCatalogPage({ searchParams }: {
  searchParams?: Promise<SkuCatalogSearchParams>;
} = {}) {
  return (
    <AppShell crumbs={["ERP", "Справочники", "Номенклатура"]}>
      {await SkuCatalogContent({ searchParams, baseHref: "/erp/spravochniki/sku" })}
    </AppShell>
  );
}
