import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Страницы App Router — тонкие обёртки: дочерние компоненты и API мокаем,
// проверяем, что страница собирает данные и монтирует нужный компонент.
// next/font/google → возвращает заглушку Inter(): без неё RootLayout падает
//   на TypeError("Inter is not a function") при импорте под vitest.
vi.mock("next/font/google", () => ({
  Inter: () => ({ variable: "--font-inter", className: "font-inter" }),
}));
vi.mock("next/link", () => ({ default: ({ children }: { children: React.ReactNode }) => <a>{children}</a> }));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));
vi.mock("next/font/google", () => ({ Inter: () => ({ variable: "mock-font", className: "mock-font" }) }));
vi.mock("@/components/app-shell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div data-testid="shell">{children}</div>,
}));
vi.mock("@/lib/role-server", () => ({ currentRole: async () => "director" }));
vi.mock("@/components/erp/module-board", () => ({
  ModuleBoard: ({ title }: { title: string }) => <div>board:{title}</div>,
}));
vi.mock("@/components/erp/logistics-tabs", () => ({
  LogisticsTabs: () => <div>logistics-tabs</div>,
}));
vi.mock("@/components/funnel/funnel-board", () => ({
  FunnelBoard: ({ title }: { title: string }) => <div>funnel:{title}</div>,
}));
vi.mock("@/components/erp/analytics-view", () => ({ AnalyticsView: () => <div>analytics-view</div> }));
vi.mock("@/components/erp/settings-view", () => ({ SettingsView: () => <div>settings-view</div> }));
vi.mock("@/components/kanban/deals-workspace", () => ({ DealsWorkspace: () => <div>deals-workspace</div> }));
vi.mock("@/components/leads/leads-workspace", () => ({ LeadsWorkspace: () => <div>leads-workspace</div> }));
vi.mock("@/components/owner-ai-insight", () => ({ OwnerAiInsight: () => <div>owner-ai-insight</div> }));
vi.mock("@/components/channels", () => ({ ChannelButtons: () => <div>channels</div> }));
vi.mock("@/components/deal-actions", () => ({ DealActions: () => <div>actions</div> }));
vi.mock("@/components/deal-ai-assistant", () => ({ DealAiAssistant: () => <div>ai</div> }));
vi.mock("@/components/deal-approvals", () => ({ DealApprovals: () => <div>approvals</div> }));
vi.mock("@/components/deal-contacts", () => ({ DealContacts: () => <div>contacts</div> }));
vi.mock("@/components/deal-documents", () => ({ DealDocuments: () => <div>documents</div> }));
vi.mock("@/components/deal-edit-button", () => ({ DealEditButton: () => <div>edit</div> }));
vi.mock("@/components/deal-items", () => ({ DealItems: () => <div>items</div> }));
vi.mock("@/components/deal-metrics", () => ({ DealMetrics: () => <div>metrics</div> }));
vi.mock("@/components/deal-messages", () => ({ DealMessages: () => <div>messages</div> }));
vi.mock("@/components/priority-badge", () => ({ PriorityBadge: () => <div>priority</div> }));
// Новые блоки карточки сделки (часть — async server components, ломают синхронный render).
vi.mock("@/components/deal-client-360", () => ({ DealClient360: () => <div>client-360</div> }));
vi.mock("@/components/deal-linked-deals", () => ({ DealLinkedDeals: () => <div>linked-deals</div> }));
vi.mock("@/components/deal-handoff", () => ({ DealHandoffBlock: () => <div>handoff</div> }));
vi.mock("@/components/deal-tasks", () => ({ DealTasks: () => <div>tasks</div> }));
// ERP-обёртки/представления, ставшие bespoke (finance/wms) или обёрткой над доской (office).
vi.mock("@/components/erp/office-view", () => ({
  OfficeView: ({ board }: { board: React.ReactNode }) => <div>{board}</div>,
}));
vi.mock("@/components/erp/finance-view", () => ({ FinanceView: () => <div>finance-view</div> }));
// MarketingPage рендерит ModuleBoard + отдельный async-board кампаний — мокаем последний.
vi.mock("@/components/erp/marketing-campaign-board", () => ({
  MarketingCampaignBoard: () => <div>campaign-board</div>,
}));
vi.mock("@/components/erp/wms-dashboard", () => ({ WmsDashboard: () => <div>wms-dashboard</div> }));
vi.mock("@/lib/wms-warehouse", () => ({ fetchDashboardServer: vi.fn().mockResolvedValue({}) }));
vi.mock("@/lib/api", () => ({
  fetchBoardStages: vi.fn().mockResolvedValue([{ id: "new", title: "Новая", color: "#000", count: 1, sum: 100, deals: [] }]),
  fetchBoardResult: vi.fn().mockResolvedValue({
    demo: false,
    stages: [{ id: "new", title: "Новая", color: "#000", count: 1, sum: 100, deals: [] }],
  }),
  fetchFunnelsServer: vi.fn().mockResolvedValue([]),
  fetchKpis: vi.fn().mockResolvedValue([]),
  fetchLeads: vi.fn().mockResolvedValue([]),
  fetchDealDetail: vi.fn().mockResolvedValue({
    number: "CRM-1", company: "ООО Карточка", description: "d", amount: 100, priority: "Средний",
    nextStep: "Звонок", contact: "Иван", datetime: "x", itemsTitle: "Номенклатура", items: [],
    messages: [], focus: false, starred: false, dealDate: "12.05.2024",
  }),
  fetchDealTasks: vi.fn().mockResolvedValue([]),
  createDealTask: vi.fn().mockResolvedValue(undefined),
  completeDealTask: vi.fn().mockResolvedValue(true),
  fetchOwnerDashboard: vi.fn(),
}));

import Home from "@/app/page";
import RootLayout from "@/app/layout";
import DealsPage from "@/app/crm/deals/page";
import DealDetailPage from "@/app/crm/deals/[id]/page";
import LeadsPage from "@/app/crm/leads/page";
import OwnerPage from "@/app/crm/owner/page";
import AnalyticsPage from "@/app/erp/analytics/page";
import FinancePage from "@/app/erp/finance/page";
import HrPage from "@/app/erp/hr/page";
import LogisticsPage from "@/app/erp/logistics/page";
import MarketingPage from "@/app/erp/marketing/page";
import ProcurementPage from "@/app/erp/procurement/page";
import ProductionPage from "@/app/erp/production/page";
import ServicePage from "@/app/erp/service/page";
import SettingsPage from "@/app/erp/settings/page";
import WmsPage from "@/app/erp/wms/page";
import OfficePage from "@/app/erp/office/page";
import LegalPage from "@/app/erp/legal/page";
import KnowledgePage from "@/app/erp/knowledge/page";
import * as api from "@/lib/api";
import { redirect } from "next/navigation";

const mock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;
afterEach(() => vi.clearAllMocks());

describe("страницы (src/app)", () => {
  it("Home редиректит на доску сделок", () => {
    Home();
    expect(redirect).toHaveBeenCalledWith("/crm/deals");
  });

  it("RootLayout оборачивает контент", () => {
    expect(RootLayout({ children: "контент" as unknown as React.ReactNode })).toBeTruthy();
  });

  it("DealsPage монтирует канбан", async () => {
    render(await DealsPage({ searchParams: Promise.resolve({}) }));
    expect(screen.getByText("deals-workspace")).toBeInTheDocument();
  });

  it("LeadsPage монтирует инбокс лидов", async () => {
    render(await LeadsPage());
    expect(screen.getByText("leads-workspace")).toBeInTheDocument();
  });

  it("DealDetailPage собирает карточку из данных", async () => {
    render(await DealDetailPage({ params: Promise.resolve({ id: "1" }) }));
    expect(screen.getByText("ООО Карточка")).toBeInTheDocument();
    expect(screen.getByText("messages")).toBeInTheDocument();
    expect(screen.getByText("documents")).toBeInTheDocument();
  });

  it("OwnerPage показывает метрики при наличии данных", async () => {
    mock(api.fetchOwnerDashboard).mockResolvedValue({
      metrics: { approvals_pending: 1, approvals_total: 1, audit_count: 0, events_count: 2, counterparties: 3, skus: 0, modules: ["sales", "wms"], widgets: [{ key: "w", title: "Воронка продаж" }] },
      stages: [
        { id: "new", title: "Новая", color: "#000", count: 1, sum: 100, deals: [] },
        { id: "won", title: "Закрыто", color: "#000", count: 2, sum: 200, deals: [] },
      ],
      kpis: [{ id: "k", label: "K", value: 1, target: 2, percent: 50, icon: "phone", tone: "blue" }],
    });
    render(await OwnerPage());
    expect(screen.getByText("Панель владельца")).toBeInTheDocument();
    expect(screen.getByText("owner-ai-insight")).toBeInTheDocument();
    expect(screen.getByText("sales")).toBeInTheDocument(); // мап modules
    expect(screen.getByText("Воронка продаж")).toBeInTheDocument(); // мап widgets
  });

  it("OwnerPage показывает заглушку без данных", async () => {
    mock(api.fetchOwnerDashboard).mockResolvedValue(null);
    render(await OwnerPage());
    expect(screen.getByText(/Нет данных/)).toBeInTheDocument();
  });

  it("OwnerPage с пустыми KPI показывает 0% плана", async () => {
    mock(api.fetchOwnerDashboard).mockResolvedValue({
      metrics: { approvals_pending: 0, approvals_total: 0, audit_count: 0, events_count: 0, counterparties: 0, skus: 0, modules: [], widgets: [] },
      stages: [],
      kpis: [],
    });
    render(await OwnerPage());
    expect(screen.getByText("0%")).toBeInTheDocument();
  });

  it("ERP-воронки монтируют FunnelBoard", () => {
    // WMS больше не воронка (bespoke-дашборд, async) — вынесен в отдельный тест ниже.
    for (const Page of [ProcurementPage, ProductionPage, HrPage, OfficePage, LegalPage, KnowledgePage]) {
      const { unmount } = render(<Page />);
      expect(screen.getByText(/^funnel:/)).toBeInTheDocument();
      unmount();
    }
  });

  it("ERP-таблицы монтируют ModuleBoard", () => {
    // Finance стал bespoke (FinanceView) — вынесен в отдельный тест ниже.
    for (const Page of [MarketingPage, ServicePage]) {
      const { unmount } = render(<Page />);
      expect(screen.getByText(/^board:/)).toBeInTheDocument();
      unmount();
    }
  });

  it("WmsPage монтирует дашборд склада (bespoke, async)", async () => {
    render(await WmsPage());
    expect(screen.getByText("wms-dashboard")).toBeInTheDocument();
  });

  it("FinancePage монтирует финансовый view (bespoke)", () => {
    render(<FinancePage />);
    expect(screen.getByText("finance-view")).toBeInTheDocument();
  });

  it("LogisticsPage монтирует вкладки логистики", () => {
    render(<LogisticsPage />);
    expect(screen.getByText("logistics-tabs")).toBeInTheDocument();
  });

  it("ERP analytics и settings монтируют свои view", () => {
    render(<AnalyticsPage />);
    expect(screen.getByText("analytics-view")).toBeInTheDocument();
    render(<SettingsPage />);
    expect(screen.getByText("settings-view")).toBeInTheDocument();
  });
});
