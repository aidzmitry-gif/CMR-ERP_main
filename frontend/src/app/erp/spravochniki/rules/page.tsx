import { AppShell } from "@/components/app-shell";
import { SpravMergeRules } from "@/components/erp/spravochniki/sprav-merge-rules";
import { fetchSurvivorshipRules } from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

export default async function SpravRulesPage() {
  const role = await currentRole();
  const rules = await fetchSurvivorshipRules(undefined, role);

  return (
    <AppShell crumbs={["ERP", "Справочники", "Правила слияния"]}>
      <SpravMergeRules rules={rules} />
    </AppShell>
  );
}
