import { AppShell } from "@/components/app-shell";
import { SpravCatalog } from "@/components/erp/spravochniki/sprav-catalog";
import {
  fetchReferenceCatalog,
  fetchRefRowsByEndpoint,
  fetchRefRowsByKey,
} from "@/lib/reference-data";
import { defaultRef, rowsSource } from "@/lib/spravochniki-catalog";
import { currentRole } from "@/lib/role-server";

export default async function SpravochnikhiPage() {
  const role = await currentRole();
  const catalog = await fetchReferenceCatalog(role);
  const firstRef = defaultRef(catalog);
  const initialRows =
    !firstRef || rowsSource(firstRef) === "lookup-only"
      ? []
      : rowsSource(firstRef) === "query-list"
        ? await fetchRefRowsByKey(firstRef.key, role)
        : await fetchRefRowsByEndpoint(firstRef.endpoint, role);

  return (
    <AppShell crumbs={["ERP", "Справочники", "Каталог"]}>
      <SpravCatalog catalog={catalog} initialRef={firstRef} initialRows={initialRows} />
    </AppShell>
  );
}
