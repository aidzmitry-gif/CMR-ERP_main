import { AppShell } from "@/components/app-shell";
import { CrmProductCatalog } from "@/components/crm-product-catalog";

export default function CrmCatalogPage() {
  return (
    <AppShell crumbs={["CRM", "Каталог-подбор"]}>
      <CrmProductCatalog />
    </AppShell>
  );
}
