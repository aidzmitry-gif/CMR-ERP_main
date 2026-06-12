import { AppShell } from "@/components/app-shell";
import { PlanMatrix } from "@/components/erp/plan-matrix";
import { fetchPlanServer } from "@/lib/production-plan";
import { currentRole } from "@/lib/role-server";

export default async function ProductionPlanningPage() {
  const role = await currentRole();
  const board = await fetchPlanServer(new Date().getFullYear(), role);
  return (
    <AppShell crumbs={["ERP", "Производство", "Планирование · план/факт"]}>
      <PlanMatrix initial={board} />
    </AppShell>
  );
}
