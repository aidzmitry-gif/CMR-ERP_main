import { AppShell } from "@/components/app-shell";
import { LeadsWorkspace } from "@/components/leads/leads-workspace";
import { fetchLeads } from "@/lib/api";
import { currentRole } from "@/lib/role-server";

export default async function LeadsPage() {
  const leads = await fetchLeads(await currentRole());
  return (
    <AppShell crumbs={["CRM", "Лиды"]}>
      <LeadsWorkspace initialLeads={leads} />
    </AppShell>
  );
}
