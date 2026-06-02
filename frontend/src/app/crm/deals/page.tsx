import { AppShell } from "@/components/app-shell";
import { DealsWorkspace } from "@/components/kanban/deals-workspace";
import { fetchBoardStages } from "@/lib/api";

export default async function DealsPage() {
  const stages = await fetchBoardStages();
  return (
    <AppShell crumbs={["CRM", "Сделки"]}>
      <DealsWorkspace initialStages={stages} />
    </AppShell>
  );
}
