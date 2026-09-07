import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchBoardResult, fetchFunnelsServer, fetchKpisResult } from "@/lib/api";
import DealsPage from "./page";

vi.mock("@/lib/api", () => ({
  fetchBoardResult: vi.fn(), fetchFunnelsServer: vi.fn(), fetchKpisResult: vi.fn(),
}));
vi.mock("@/lib/role-server", () => ({
  currentRole: vi.fn().mockResolvedValue("sales"),
  currentAccessToken: vi.fn().mockResolvedValue("synthetic-test-token"),
}));
vi.mock("@/components/app-shell", () => ({ AppShell: vi.fn() }));
vi.mock("@/components/kanban/deals-workspace", () => ({ DealsWorkspace: vi.fn() }));
vi.mock("@/components/kanban/company-switcher", () => ({ CompanySwitcher: vi.fn() }));
vi.mock("@/components/kanban/filters-menu", () => ({ FiltersMenu: vi.fn() }));
vi.mock("@/components/kanban/funnel-tabs", () => ({ FunnelTabs: vi.fn() }));

describe("deal board and KPI access are independent", () => {
  beforeEach(() => {
    vi.mocked(fetchBoardResult).mockResolvedValue({ stages: [], demo: false });
    vi.mocked(fetchKpisResult).mockResolvedValue({ kpis: [], demo: false, authError: true });
    vi.mocked(fetchFunnelsServer).mockResolvedValue([{ code: "new_clients", title: "Новые" }]);
  });

  it.each(["new_clients", "all"])("keeps permitted board available when KPIs deny access: %s", async (funnel) => {
    const page = await DealsPage({ searchParams: Promise.resolve({ funnel }) });
    const workspace = page.props.children as ReactElement<{ authError?: boolean; kpiAccessDenied?: boolean; initialKpis: unknown[] }>;
    expect(Boolean(workspace.props.authError)).toBe(false);
    expect(workspace.props.kpiAccessDenied).toBe(true);
    expect(workspace.props.initialKpis).toEqual([]);
    expect(fetchBoardResult).toHaveBeenCalledWith("sales", "new_clients", "synthetic-test-token");
  });

  it("preserves a board permission failure even when KPIs succeed", async () => {
    vi.mocked(fetchBoardResult).mockResolvedValue({ stages: [], demo: false, authError: true });
    vi.mocked(fetchKpisResult).mockResolvedValue({ kpis: [], demo: false });
    const page = await DealsPage({ searchParams: Promise.resolve({}) });
    const workspace = page.props.children as ReactElement<{ authError?: boolean }>;
    expect(workspace.props.authError).toBe(true);
  });
});
