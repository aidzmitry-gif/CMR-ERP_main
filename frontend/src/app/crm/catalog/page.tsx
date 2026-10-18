import { AppShell } from "@/components/app-shell";
import { SkuCatalogContent, type SkuCatalogSearchParams } from "@/components/erp/spravochniki/sprav-sku-catalog";

export default async function CrmCatalogPage({ searchParams }: {
  searchParams?: Promise<SkuCatalogSearchParams>;
}) {
  return (
    <AppShell crumbs={["CRM", "Каталог-подбор"]}>
      <p className="mx-6 mt-6 rounded-xl bg-surface p-4 text-sm text-muted">
        Цены и остатки по складам здесь пока неизвестны. Для оформления счёта откройте сделку.
      </p>
      {await SkuCatalogContent({ searchParams, baseHref: "/crm/catalog" })}
    </AppShell>
  );
}
