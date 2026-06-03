import { AppShell } from "@/components/app-shell";
import { LeadsWorkspace } from "@/components/leads/leads-workspace";
import { fetchLeads } from "@/lib/api";

export default async function LeadsPage() {
  const leads = await fetchLeads();
  return (
    <AppShell crumbs={["CRM", "Лиды"]}>
      <LeadsWorkspace initialLeads={leads} />
    </AppShell>
  );
}
