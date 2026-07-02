import { AppShell } from "@/components/app-shell";
import { CompanySwitcher } from "@/components/kanban/company-switcher";
import { DealsWorkspace } from "@/components/kanban/deals-workspace";
import { FunnelTabs } from "@/components/kanban/funnel-tabs";
import { fetchBoardStages, fetchFunnels, fetchKpis } from "@/lib/api";
import { currentRole } from "@/lib/role-server";

export default async function DealsPage({
  searchParams,
}: {
  searchParams: Promise<{ funnel?: string }>;
}) {
  const { funnel } = await searchParams;
  const activeFunnel = funnel ?? "new_clients";
  const role = await currentRole();

  if (activeFunnel === "all") {
    // «Все вместе» (мокап sales-board-mockup.html, COMBINED): доска каждой воронки —
    // одна под другой. Справочник воронок — /sales/funnels (не хардкодим список).
    const [funnels, kpis] = await Promise.all([fetchFunnels(), fetchKpis(role)]);
    const sections = await Promise.all(
      funnels.map(async (f) => ({
        code: f.code,
        title: f.title,
        stages: await fetchBoardStages(role, f.code),
      })),
    );
    return (
      <AppShell crumbs={["CRM", "Сделки"]}>
        <DealsWorkspace
          key="all"
          initialStages={sections[0]?.stages ?? []}
          initialKpis={kpis}
          combinedStages={sections}
          funnelTabs={<FunnelTabs active={activeFunnel} />}
          switcher={<CompanySwitcher />}
        />
      </AppShell>
    );
  }

  // SSR: стадии для выбранной воронки + KPI; key прокидывает funnel в DealsWorkspace,
  // чтобы клиентский стейт колонок сбрасывался при переключении воронки.
  const [stages, kpis] = await Promise.all([fetchBoardStages(role, activeFunnel), fetchKpis(role)]);
  return (
    <AppShell crumbs={["CRM", "Сделки"]}>
      {/* CurrencyProvider поднят в app/crm/layout.tsx — общий на весь CRM */}
      <DealsWorkspace
        key={activeFunnel}
        initialStages={stages}
        initialKpis={kpis}
        funnelTabs={<FunnelTabs active={activeFunnel} />}
        switcher={<CompanySwitcher />}
      />
    </AppShell>
  );
}
