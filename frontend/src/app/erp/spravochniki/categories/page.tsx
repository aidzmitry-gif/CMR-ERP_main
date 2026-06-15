import { AppShell } from "@/components/app-shell";
import { SpravCategories } from "@/components/erp/spravochniki/sprav-categories";
import { fetchNomenclatureGroups } from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

export default async function CategoriesPage() {
  const role = await currentRole();
  const groups = await fetchNomenclatureGroups({ roles: role });

  return (
    <AppShell crumbs={["ERP", "Справочники", "Группы номенклатуры"]}>
      <SpravCategories initial={groups} />
    </AppShell>
  );
}
