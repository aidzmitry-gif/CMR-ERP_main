import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Страницы App Router — тонкие обёртки: дочерние компоненты и API мокаем,
// проверяем, что страница собирает данные и монтирует нужный компонент.
vi.mock("next/link", () => ({ default: ({ children }: { children: React.ReactNode }) => <a>{children}</a> }));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));
vi.mock("@/components/app-shell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div data-testid="shell">{children}</div>,
}));
vi.mock("@/components/erp/module-board", () => ({
  ModuleBoard: ({ title, action }: { title: string; action?: { path: (row: { id: number }) => string } }) => {
    if (action) action.path({ id: 1 }); // вызвать билдер пути действия (для покрытия)
    return <div>board:{title}</div>;
  },
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
vi.mock("@/components/deal-messages", () => ({ DealMessages: () => <div>messages</div> }));
vi.mock("@/components/priority-badge", () => ({ PriorityBadge: () => <div>priority</div> }));
vi.mock("@/lib/api", () => ({
  fetchBoardStages: vi.fn().mockResolvedValue([{ id: "new", title: "Новая", color: "#000", count: 1, sum: 100, deals: [] }]),
  fetchKpis: vi.fn().mockResolvedValue([]),
  fetchLeads: vi.fn().mockResolvedValue([]),
  fetchDealDetail: vi.fn().mockResolvedValue({
    number: "CRM-1", company: "ООО Карточка", description: "d", amount: 100, priority: "Средний",
    nextStep: "Звонок", contact: "Иван", datetime: "x", itemsTitle: "Номенклатура", items: [],
    messages: [], focus: false, starred: false, dealDate: "12.05.2024",
  }),
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
    render(await DealsPage());
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
      metrics: { approvals_pending: 1, approvals_total: 1, audit_count: 0, events_count: 2, counterparties: 3, skus: 0, modules: [], widgets: [] },
      stages: [
        { id: "new", title: "Новая", color: "#000", count: 1, sum: 100, deals: [] },
        { id: "won", title: "Закрыто", color: "#000", count: 2, sum: 200, deals: [] },
      ],
      kpis: [{ id: "k", label: "K", value: 1, target: 2, percent: 50, icon: "phone", tone: "blue" }],
    });
    render(await OwnerPage());
    expect(screen.getByText("Панель владельца")).toBeInTheDocument();
    expect(screen.getByText("owner-ai-insight")).toBeInTheDocument();
  });

  it("OwnerPage показывает заглушку без данных", async () => {
    mock(api.fetchOwnerDashboard).mockResolvedValue(null);
    render(await OwnerPage());
    expect(screen.getByText(/Нет данных/)).toBeInTheDocument();
  });

  it("ERP-страницы монтируют ModuleBoard", () => {
    for (const Page of [ProcurementPage, ProductionPage, WmsPage, LogisticsPage, FinancePage, MarketingPage, ServicePage, HrPage]) {
      const { unmount } = render(<Page />);
      expect(screen.getByText(/^board:/)).toBeInTheDocument();
      unmount();
    }
  });

  it("ERP analytics и settings монтируют свои view", () => {
    render(<AnalyticsPage />);
    expect(screen.getByText("analytics-view")).toBeInTheDocument();
    render(<SettingsPage />);
    expect(screen.getByText("settings-view")).toBeInTheDocument();
  });
});
