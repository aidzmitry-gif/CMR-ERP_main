import { fireEvent, render, screen } from "@testing-library/react";
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

import { FiltersMenu } from "@/components/kanban/filters-menu";

describe("FiltersMenu", () => {
  beforeEach(() => {
    navigation.replace.mockReset();
    navigation.searchParams = new URLSearchParams();
  });

  it("сохраняет текущую воронку при выборе приоритета", () => {
    navigation.searchParams = new URLSearchParams("funnel=repeat_clients");
    render(<FiltersMenu />);

    fireEvent.click(screen.getByRole("button", { name: /^Фильтры/ }));
    fireEvent.click(screen.getByRole("button", { name: "Высокий", exact: true }));

    expect(navigation.replace).toHaveBeenCalledWith(
      `/crm/deals?${new URLSearchParams({ funnel: "repeat_clients", priority: "Высокий" }).toString()}`,
    );
    expect(screen.queryByRole("button", { name: "Средний", exact: true })).not.toBeInTheDocument();
  });

  it("сбрасывает только приоритет и оставляет остальные параметры", () => {
    navigation.searchParams = new URLSearchParams("funnel=new_clients&priority=Высокий");
    render(<FiltersMenu />);

    expect(screen.getByText("Высокий")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Фильтры/ }));
    fireEvent.click(screen.getByRole("button", { name: "Все", exact: true }));

    expect(navigation.replace).toHaveBeenCalledWith("/crm/deals?funnel=new_clients");
  });
});
