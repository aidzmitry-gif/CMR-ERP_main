import { AppShell } from "@/components/app-shell";
import { SpravMergeRules } from "@/components/erp/spravochniki/sprav-merge-rules";
import { backendAuthHeaders } from "@/lib/auth-headers-server";
import { fetchSurvivorshipRules } from "@/lib/reference-data";
import { currentRole } from "@/lib/role-server";

export default async function SpravRulesPage() {
  const role = await currentRole();
  const authHeaders = await backendAuthHeaders(role);
  const rules = await fetchSurvivorshipRules(undefined, role, authHeaders);

  return (
    <AppShell crumbs={["ERP", "Справочники", "Правила слияния"]}>
      <SpravMergeRules rules={rules} />
    </AppShell>
  );
}
