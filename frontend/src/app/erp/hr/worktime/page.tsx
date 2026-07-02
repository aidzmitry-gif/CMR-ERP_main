import { AppShell } from "@/components/app-shell";
import { WorktimeView } from "@/components/erp/worktime-view";

export default function WorktimePage() {
  return (
    <AppShell crumbs={["ERP", "HR", "Учёт времени"]}>
      <WorktimeView />
    </AppShell>
  );
}
