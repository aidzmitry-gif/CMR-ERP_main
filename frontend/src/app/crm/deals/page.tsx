import { AppShell } from "@/components/app-shell";
import { DealsWorkspace } from "@/components/kanban/deals-workspace";
import { fetchBoardStages, fetchKpis } from "@/lib/api";

export default async function DealsPage() {
  const [stages, kpis] = await Promise.all([fetchBoardStages(), fetchKpis()]);
  return (
    <AppShell crumbs={["CRM", "Сделки"]}>
      <DealsWorkspace initialStages={stages} kpis={kpis} />
    </AppShell>
  );
}
