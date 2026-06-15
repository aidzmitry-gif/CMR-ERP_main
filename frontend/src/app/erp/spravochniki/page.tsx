import { AppShell } from "@/components/app-shell";
import { SpravCatalog } from "@/components/erp/spravochniki/sprav-catalog";
import { fetchReferenceCatalog, fetchRefRowsByEndpoint } from "@/lib/reference-data";
import { defaultRef } from "@/lib/spravochniki-catalog";
import { currentRole } from "@/lib/role-server";

export default async function SpravochnikhiPage() {
  const role = await currentRole();
  const catalog = await fetchReferenceCatalog(role);
  const firstRef = defaultRef(catalog);
  const initialRows = firstRef
    ? await fetchRefRowsByEndpoint(firstRef.endpoint, role)
    : [];

  return (
    <AppShell crumbs={["ERP", "Справочники", "Каталог"]}>
      <SpravCatalog catalog={catalog} initialRef={firstRef} initialRows={initialRows} />
    </AppShell>
  );
}
