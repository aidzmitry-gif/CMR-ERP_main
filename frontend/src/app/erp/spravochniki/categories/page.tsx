import { AppShell } from "@/components/app-shell";
import { SpravCategories } from "@/components/erp/spravochniki/sprav-categories";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { fetchNomenclatureGroups } from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

export default async function CategoriesPage() {
  const role = await currentRole();
  const authHeaders = await backendAuthHeaders(role);
  const groups = await fetchNomenclatureGroups({ roles: role }, authHeaders);

  return (
    <AppShell crumbs={["ERP", "Справочники", "Группы номенклатуры"]}>
      <SpravCategories initial={groups} />
    </AppShell>
  );
}
