import { AppShell } from "@/components/app-shell";
import { LogisticsTabs } from "@/components/erp/logistics-tabs";

export default function LogisticsPage() {
  return (
    <AppShell crumbs={["ERP", "Логистика"]}>
      <LogisticsTabs />
    </AppShell>
  );
}
