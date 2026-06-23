import { AppShell } from "@/components/app-shell";
import { CatalogPicker } from "@/components/catalog/catalog-picker";

export default function Page() {
  return (
    <AppShell crumbs={["CRM", "Каталог-подбор"]}>
      <CatalogPicker />
    </AppShell>
  );
}
