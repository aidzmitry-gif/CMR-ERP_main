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
  searchParams: Promise<{ funnel?: string; owner_id?: string }>;
}) {
  const { funnel, owner_id } = await searchParams;
  const activeFunnel = funnel ?? "new_clients";
  const role = await currentRole();
  // Владелец плана (dev/демо через ?owner_id=) — «План» скорборда из согласованного PlanTarget.
  // Нет параметра → undefined → доска без изменений (как раньше). ponytail: связать с логином.
  const ownerId = owner_id ? Number.parseInt(owner_id, 10) || undefined : undefined;

  // key на FunnelTabs обязателен: элемент создаётся в server-компоненте DealsPage и уезжает
  // пропом в client-компонент DealsWorkspace через RSC-границу. При клиентском рендере React
  // (dev) заново валидирует десериализованный элемент и без key ложно ругается «child in a
  // list should have a unique key» (флаг validated с сервера не сериализуется). Fires только
  // на клиенте — на SSR элемент уже помечен валидным. Одна константа на обе ветки заодно.
  const funnelTabs = <FunnelTabs key="funnel-tabs" active={activeFunnel} />;

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
          funnelTabs={funnelTabs}
          ownerId={ownerId}
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
        funnelTabs={funnelTabs}
        ownerId={ownerId}
      />
    </AppShell>
  );
}
