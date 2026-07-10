import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const navigation = vi.hoisted(() => ({
  pathname: "/crm/deals",
  replace: vi.fn(),
  searchParams: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => ({ replace: navigation.replace }),
  useSearchParams: () => navigation.searchParams,
}));
vi.mock("@/lib/api", () => ({ fetchFunnels: vi.fn() }));

import { FunnelTabs } from "@/components/kanban/funnel-tabs";
import { fetchFunnels } from "@/lib/api";

const mockFetchFunnels = fetchFunnels as ReturnType<typeof vi.fn>;

describe("FunnelTabs", () => {
  beforeEach(() => {
    navigation.replace.mockReset();
    navigation.searchParams = new URLSearchParams();
    mockFetchFunnels.mockReset();
  });

  it("скрывается, когда доступна только одна воронка", async () => {
    mockFetchFunnels.mockResolvedValue([{ code: "new_clients", title: "Новые", active_deals: 3 }]);
    render(<FunnelTabs />);

    await waitFor(() => expect(mockFetchFunnels).toHaveBeenCalledOnce());
    expect(screen.queryByRole("combobox", { name: "Воронка" })).not.toBeInTheDocument();
  });

  it("переключает воронку, сохраняя другие параметры URL", async () => {
    navigation.searchParams = new URLSearchParams("priority=Высокий");
    mockFetchFunnels.mockResolvedValue([
      { code: "new_clients", title: "Новые", active_deals: 3 },
      { code: "repeat_clients", title: "Повторные", active_deals: 2 },
    ]);
    render(<FunnelTabs active="new_clients" />);

    const select = await screen.findByRole("combobox", { name: "Воронка" });
    fireEvent.change(select, { target: { value: "repeat_clients" } });

    expect(navigation.replace).toHaveBeenCalledWith(
      `/crm/deals?${new URLSearchParams({ priority: "Высокий", funnel: "repeat_clients" }).toString()}`,
    );
  });

  it("не показывает контрол, если загрузка воронок завершилась ошибкой", async () => {
    mockFetchFunnels.mockRejectedValue(new Error("network unavailable"));
    render(<FunnelTabs />);

    await waitFor(() => expect(mockFetchFunnels).toHaveBeenCalledOnce());
    expect(screen.queryByRole("combobox", { name: "Воронка" })).not.toBeInTheDocument();
  });
});
