import { AppShell } from "@/components/app-shell";
import { loadLeadsServer } from "@/components/leads/leads-load";
import { LeadsWorkspace } from "@/components/leads/leads-workspace";
import { currentAccessToken, currentRole } from "@/lib/role-server";

export default async function LeadsPage() {
  const role = await currentRole();
  const token = (await currentAccessToken()) ?? undefined;
  const { state: loadState, leads } = await loadLeadsServer(role, token);
  return (
    <AppShell crumbs={["CRM", "Лиды"]}>
      <LeadsWorkspace initialLeads={leads} initialLoadState={loadState} />
    </AppShell>
  );
}
