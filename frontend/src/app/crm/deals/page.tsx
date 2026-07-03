import { Image as ImageIcon, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { CompanySwitcher } from "@/components/kanban/company-switcher";
import { DealsWorkspace } from "@/components/kanban/deals-workspace";
import { FiltersMenu } from "@/components/kanban/filters-menu";
import { FunnelTabs } from "@/components/kanban/funnel-tabs";
import { fetchBoardResult, fetchFunnelsServer, fetchKpis } from "@/lib/api";
import { currentRole } from "@/lib/role-server";

/** Переключатель ЮЛ + «Фильтры» + «Стадии»/«Лого» (иконки) — правее хлебных крошек
 *  «CRM / Сделки», в одну строку (решение оператора: раньше жили в тулбаре доски). */
function DealsHeaderActions() {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <CompanySwitcher />
      <FiltersMenu />
      <Link
        href="/crm/deals/stages"
        title="Стадии"
        className="flex h-9 w-9 items-center justify-center rounded-lg border border-line text-muted hover:bg-sunken hover:text-ink"
      >
        <SlidersHorizontal size={16} />
      </Link>
      <Link
        href="/crm/deals/branding"
        title="Лого компании (для счетов)"
        className="flex h-9 w-9 items-center justify-center rounded-lg border border-line text-muted hover:bg-sunken hover:text-ink"
      >
        <ImageIcon size={16} />
      </Link>
    </div>
  );
}

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
    const [funnels, kpis] = await Promise.all([fetchFunnelsServer(role), fetchKpis(role)]);
    const sections = await Promise.all(
      funnels.map(async (f) => ({
        code: f.code,
        title: f.title,
        ...(await fetchBoardResult(role, f.code)),
      })),
    );
    return (
      <AppShell crumbs={["CRM", "Сделки"]} headerActions={<DealsHeaderActions />}>
        <DealsWorkspace
          key="all"
          initialStages={sections[0]?.stages ?? []}
          initialKpis={kpis}
          combinedStages={sections}
          demoData={sections.some((r) => r.demo)}
          funnelTabs={<FunnelTabs active={activeFunnel} />}
        />
      </AppShell>
    );
  }

  // SSR: стадии для выбранной воронки + KPI; key прокидывает funnel в DealsWorkspace,
  // чтобы клиентский стейт колонок сбрасывался при переключении воронки.
  const [board, kpis] = await Promise.all([fetchBoardResult(role, activeFunnel), fetchKpis(role)]);
  return (
    <AppShell crumbs={["CRM", "Сделки"]} headerActions={<DealsHeaderActions />}>
      {/* CurrencyProvider поднят в app/crm/layout.tsx — общий на весь CRM */}
      <DealsWorkspace
        key={activeFunnel}
        initialStages={board.stages}
        initialKpis={kpis}
        demoData={board.demo}
        funnelTabs={<FunnelTabs active={activeFunnel} />}
      />
    </AppShell>
  );
}
