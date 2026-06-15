import { AppShell } from "@/components/app-shell";
import { SpravAi } from "@/components/erp/spravochniki/sprav-ai";
import { fetchAiCatalog } from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

export default async function SpravAiPage() {
  const role = await currentRole();
  const catalog = await fetchAiCatalog(role);

  return (
    <AppShell crumbs={["ERP", "Справочники", "AI-доступ"]}>
      <SpravAi initial={catalog} />
    </AppShell>
  );
}
