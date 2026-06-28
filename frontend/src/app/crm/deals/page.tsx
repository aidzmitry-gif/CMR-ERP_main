import { AppShell } from "@/components/app-shell";
import { CompanySwitcher } from "@/components/kanban/company-switcher";
import { DealsWorkspace } from "@/components/kanban/deals-workspace";
import { FunnelTabs } from "@/components/kanban/funnel-tabs";
import { fetchBoardStages, fetchKpis } from "@/lib/api";
import { currentRole } from "@/lib/role-server";

export default async function DealsPage({
  searchParams,
}: {
  searchParams: Promise<{ funnel?: string }>;
}) {
  const { funnel } = await searchParams;
  const activeFunnel = funnel ?? "new_clients";
  const role = await currentRole();
  // SSR: стадии для выбранной воронки + KPI; key прокидывает funnel в DealsWorkspace,
  // чтобы клиентский стейт колонок сбрасывался при переключении воронки.
  const [stages, kpis] = await Promise.all([fetchBoardStages(role, activeFunnel), fetchKpis(role)]);
  return (
    <AppShell crumbs={["CRM", "Сделки"]}>
      <div className="px-6 pt-3">
        <FunnelTabs active={activeFunnel} />
      </div>
      {/* CurrencyProvider поднят в app/crm/layout.tsx — общий на весь CRM */}
      <DealsWorkspace
        key={activeFunnel}
        initialStages={stages}
        initialKpis={kpis}
        switcher={<CompanySwitcher />}
      />
    </AppShell>
  );
}
