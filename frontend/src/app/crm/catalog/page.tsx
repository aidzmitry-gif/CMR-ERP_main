import { AppShell } from "@/components/app-shell";
import { SkuCatalogContent, type SkuCatalogSearchParams } from "@/components/erp/spravochniki/sprav-sku-catalog";

export default async function CrmCatalogPage({ searchParams }: {
  searchParams?: Promise<SkuCatalogSearchParams>;
}) {
  return (
    <AppShell crumbs={["CRM", "Каталог-подбор"]}>
      <div className="min-w-0 flex-1">
        <div className="mx-auto max-w-[1280px] px-4 pt-5 md:px-6 md:pt-6">
          <p className="rounded-xl border border-line bg-surface px-4 py-3 text-sm leading-relaxed text-muted">
            Цены и остатки по складам здесь пока неизвестны. Для оформления счёта откройте сделку.
          </p>
        </div>
        {await SkuCatalogContent({ searchParams, baseHref: "/crm/catalog" })}
      </div>
    </AppShell>
  );
}
