import { AppShell } from "@/components/app-shell";
import { HrOkkView } from "@/components/erp/hr-okk-view";

export default function HrOkkPage() {
  return (
    <AppShell crumbs={["ERP", "HR", "ОКК"]}>
      <HrOkkView />
    </AppShell>
  );
}
