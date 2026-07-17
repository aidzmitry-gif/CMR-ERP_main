import { AppShell } from "@/components/app-shell";
import { LeadsWorkspace } from "@/components/leads/leads-workspace";
import { fetchLeads } from "@/lib/api";
import { currentAccessToken, currentRole } from "@/lib/role-server";

export default async function LeadsPage() {
  const role = await currentRole();
  const token = (await currentAccessToken()) ?? undefined;
  const leads = await fetchLeads(role, token);
  return (
    <AppShell crumbs={["CRM", "Лиды"]}>
      <LeadsWorkspace initialLeads={leads} />
    </AppShell>
  );
}
