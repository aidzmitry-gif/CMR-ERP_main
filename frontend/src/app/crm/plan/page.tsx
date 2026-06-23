import { AppShell } from "@/components/app-shell";
import { PlanBuilder } from "@/components/plan/plan-builder";

export default function Page() {
  return (
    <AppShell crumbs={["CRM", "Конструктор плана"]}>
      <PlanBuilder />
    </AppShell>
  );
}
