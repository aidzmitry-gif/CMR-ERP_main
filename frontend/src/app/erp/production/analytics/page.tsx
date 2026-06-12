import { AppShell } from "@/components/app-shell";
import { ProductionAnalyticsView } from "@/components/erp/production-analytics-view";
import { fetchAnalyticsServer } from "@/lib/production-analytics";
import { currentRole } from "@/lib/role-server";

export default async function ProductionAnalyticsPage() {
  const role = await currentRole();
  const data = await fetchAnalyticsServer(new Date().getFullYear(), role);
  return (
    <AppShell crumbs={["ERP", "Производство", "Аналитика производства"]}>
      <ProductionAnalyticsView initial={data} />
    </AppShell>
  );
}
