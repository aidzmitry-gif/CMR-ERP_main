import { AppShell } from "@/components/app-shell";
import { OtkPanel } from "@/components/erp/otk-panel";
import { fetchDecisionsServer, fetchStatsServer } from "@/lib/production-otk";
import { currentRole } from "@/lib/role-server";

export default async function ProductionOtkPage() {
  const role = await currentRole();
  const [stats, journal] = await Promise.all([
    fetchStatsServer(role),
    fetchDecisionsServer(role),
  ]);

  return (
    <AppShell crumbs={["ERP", "Производство", "ОТК · контроль качества"]}>
      <OtkPanel initialStats={stats} initialJournal={journal} />
    </AppShell>
  );
}
