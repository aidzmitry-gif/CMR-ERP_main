import { AppShell } from "@/components/app-shell";
import { CompanySwitcher } from "@/components/kanban/company-switcher";
import { CurrencyProvider } from "@/components/kanban/currency-context";
import { DealsWorkspace } from "@/components/kanban/deals-workspace";
import { fetchBoardStages, fetchKpis } from "@/lib/api";
import { currentRole } from "@/lib/role-server";

export default async function DealsPage() {
  const role = await currentRole();
  const [stages, kpis] = await Promise.all([fetchBoardStages(role), fetchKpis(role)]);
  return (
    <AppShell crumbs={["CRM", "Сделки"]}>
      <CurrencyProvider>
        <DealsWorkspace initialStages={stages} initialKpis={kpis} switcher={<CompanySwitcher />} />
      </CurrencyProvider>
    </AppShell>
  );
}
