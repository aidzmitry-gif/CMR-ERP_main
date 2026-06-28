import { AppShell } from "@/components/app-shell";
import { FinanceView } from "@/components/erp/finance-view";

export default function FinancePage() {
  return (
    <AppShell crumbs={["ERP", "Финансы"]}>
      <FinanceView />
    </AppShell>
  );
}
