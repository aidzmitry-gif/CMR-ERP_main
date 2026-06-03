import { AppShell } from "@/components/app-shell";
import { AnalyticsView } from "@/components/erp/analytics-view";

export default function AnalyticsPage() {
  return (
    <AppShell crumbs={["ERP", "Аналитика"]}>
      <AnalyticsView />
    </AppShell>
  );
}
