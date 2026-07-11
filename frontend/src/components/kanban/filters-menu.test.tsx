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
vi.mock("@/lib/api", () => ({
  fetchLeadManagers: vi
    .fn()
    .mockResolvedValue([{ name: "Орлов И.", regions: [], products: [], load: 1 }]),
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
      { scroll: false },
    );
    // Мульти-выбор: меню НЕ закрывается после клика — можно выбрать ещё фильтры.
    expect(screen.getByRole("button", { name: "Средний", exact: true })).toBeInTheDocument();
  });

  it("сбрасывает только приоритет и оставляет остальные параметры", () => {
    navigation.searchParams = new URLSearchParams("funnel=new_clients&priority=Высокий");
    render(<FiltersMenu />);

    expect(screen.getByText("Высокий")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Фильтры/ }));
    // «Все» есть в каждой секции (Приоритет/Ответственный/Внимание) — первый сбрасывает приоритет
    fireEvent.click(screen.getAllByRole("button", { name: "Все", exact: true })[0]);

    expect(navigation.replace).toHaveBeenCalledWith("/crm/deals?funnel=new_clients", {
      scroll: false,
    });
  });

  it("секция «Ответственный»: выбирает менеджера из fetchLeadManagers → ?owner=", async () => {
    render(<FiltersMenu />);

    fireEvent.click(screen.getByRole("button", { name: /^Фильтры/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Орлов И." }));

    expect(navigation.replace).toHaveBeenCalledWith(
      `/crm/deals?${new URLSearchParams({ owner: "Орлов И." }).toString()}`,
      { scroll: false },
    );
  });

  it("секция «Внимание»: «Просроченные» → ?attn=overdue, «Без шага» → ?attn=no_step, «Реанимировать» → ?attn=revive", () => {
    render(<FiltersMenu />);

    // Меню больше не закрывается по клику — все три варианта проверяются за одно открытие
    // (каждый следующий клик перезаписывает attn, накапливаясь через draftRef).
    fireEvent.click(screen.getByRole("button", { name: /^Фильтры/ }));
    fireEvent.click(screen.getByRole("button", { name: "Просроченные" }));
    expect(navigation.replace).toHaveBeenCalledWith("/crm/deals?attn=overdue", { scroll: false });

    fireEvent.click(screen.getByRole("button", { name: "Без шага" }));
    expect(navigation.replace).toHaveBeenCalledWith("/crm/deals?attn=no_step", { scroll: false });

    fireEvent.click(screen.getByRole("button", { name: "Реанимировать" }));
    expect(navigation.replace).toHaveBeenCalledWith("/crm/deals?attn=revive", { scroll: false });
  });

  it("3 фильтра за одно открытие: приоритет + ответственный + внимание накапливаются, «Готово» закрывает", async () => {
    render(<FiltersMenu />);

    fireEvent.click(screen.getByRole("button", { name: /^Фильтры/ }));
    fireEvent.click(screen.getByRole("button", { name: "Высокий", exact: true }));
    fireEvent.click(await screen.findByRole("button", { name: "Орлов И." }));
    fireEvent.click(screen.getByRole("button", { name: "Просроченные" }));

    // useSearchParams в моке статичен — накопление держит draftRef (в бою его синкает URL).
    expect(navigation.replace).toHaveBeenLastCalledWith(
      `/crm/deals?${new URLSearchParams({
        priority: "Высокий",
        owner: "Орлов И.",
        attn: "overdue",
      }).toString()}`,
      { scroll: false },
    );

    fireEvent.click(screen.getByRole("button", { name: "Готово" }));
    expect(screen.queryByRole("button", { name: "Готово" })).not.toBeInTheDocument();
  });

  it("активные owner/attn видны бейджами на кнопке «Фильтры»", () => {
    navigation.searchParams = new URLSearchParams("owner=Орлов И.&attn=no_step");
    render(<FiltersMenu />);

    const btn = screen.getByRole("button", { name: /^Фильтры/ });
    expect(btn).toHaveTextContent("Орлов И.");
    expect(btn).toHaveTextContent("Без шага");
  });
});
