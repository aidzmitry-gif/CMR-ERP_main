import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));
// Регрессия A2: если кто-то вернёт ChannelRow на карточку — мок отрендерит testid и тест упадёт.
vi.mock("@/components/channels", () => ({ ChannelRow: () => <div data-testid="channels" /> }));
vi.mock("@/lib/api", () => ({
  fetchLeadManagers: vi
    .fn()
    .mockResolvedValue([{ name: "Орлов И.", regions: [], products: [], load: 1 }]),
}));

import { DealCard } from "@/components/kanban/deal-card";
import type { Deal } from "@/lib/types";

const deal: Deal = {
  id: "1",
  number: "CRM-1",
  company: "ООО Карта",
  description: "Поставка металлопроката",
  amount: 850000,
  priority: "Высокий",
  owner: "Иванов И.И.",
  nextStep: "Звонок",
};

describe("DealCard", () => {
  it("показывает номер, компанию, приоритет, сумму и следующий шаг", () => {
    render(<DealCard deal={deal} />);
    expect(screen.getByText("№ CRM-1")).toBeInTheDocument();
    expect(screen.getByText("ООО Карта")).toBeInTheDocument();
    expect(screen.getByText("Высокий")).toBeInTheDocument();
    expect(screen.getByText(/850\D?000/)).toBeInTheDocument();
    expect(screen.getByText(/Звонок/)).toBeInTheDocument();
  });

  it("не содержит пилюль «Фокус»/«Приоритет» и ряда каналов (чистка карточки)", () => {
    render(<DealCard deal={deal} />);
    expect(screen.queryByText("Фокус")).toBeNull();
    expect(screen.queryByText("Приоритет")).toBeNull(); // бейдж приоритета остаётся («Высокий»)
    expect(screen.queryByTestId("channels")).toBeNull();
  });

  it("actBucket=today рисует чип «Сегодня», overdue — «Просрочено», без actBucket чипов нет", () => {
    const { rerender } = render(<DealCard deal={deal} actBucket="today" />);
    expect(screen.getByText("Сегодня")).toBeInTheDocument();
    rerender(<DealCard deal={deal} actBucket="overdue" />);
    expect(screen.getByText("Просрочено")).toBeInTheDocument();
    expect(screen.queryByText("Сегодня")).toBeNull();
    rerender(<DealCard deal={deal} />);
    expect(screen.queryByText("Просрочено")).toBeNull();
  });

  it("noStep рисует маркер «нет шага»", () => {
    const { rerender } = render(<DealCard deal={{ ...deal, nextStep: undefined }} noStep />);
    expect(screen.getByText("нет шага")).toBeInTheDocument();
    rerender(<DealCard deal={deal} />);
    expect(screen.queryByText("нет шага")).toBeNull();
  });

  it("todo сведён к строке «След. шаг» с датой/временем и строкой номенклатуры (без «Редактировать товар»)", () => {
    render(
      <DealCard
        deal={{
          ...deal,
          todo: "Согласовать КП",
          actionDate: "12.05",
          actionTime: "14:00",
          itemsLabel: "АКБ 6СТ-190",
          itemsCount: 3,
        }}
      />,
    );
    expect(screen.getByText("Согласовать КП · 12.05 · 14:00")).toBeInTheDocument();
    expect(screen.getByText("3 поз. · АКБ 6СТ-190")).toBeInTheDocument();
    expect(screen.queryByText("Что нужно сделать:")).toBeNull();
    expect(screen.queryByText("Редактировать товар")).toBeNull();
  });

  it("меню ⋯: «В избранное» зовёт onUpdate({starred:true})", () => {
    const onUpdate = vi.fn();
    render(<DealCard deal={deal} onUpdate={onUpdate} />);
    fireEvent.click(screen.getByRole("button", { name: "Меню карточки" }));
    fireEvent.click(screen.getByRole("button", { name: "В избранное" }));
    expect(onUpdate).toHaveBeenCalledWith({ starred: true });
  });

  it("меню ⋯: подсписок «Приоритет» зовёт onUpdate({priority})", () => {
    const onUpdate = vi.fn();
    render(<DealCard deal={deal} onUpdate={onUpdate} />);
    fireEvent.click(screen.getByRole("button", { name: "Меню карточки" }));
    fireEvent.click(screen.getByRole("button", { name: "Приоритет" }));
    fireEvent.click(screen.getByRole("button", { name: /Средний/ }));
    expect(onUpdate).toHaveBeenCalledWith({ priority: "Средний" });
  });

  it("меню ⋯: подсписок «Ответственный» грузит менеджеров и зовёт onUpdate({owner})", async () => {
    const onUpdate = vi.fn();
    render(<DealCard deal={deal} onUpdate={onUpdate} />);
    fireEvent.click(screen.getByRole("button", { name: "Меню карточки" }));
    fireEvent.click(screen.getByRole("button", { name: "Ответственный" }));
    fireEvent.click(await screen.findByRole("button", { name: /Орлов И\./ }));
    expect(onUpdate).toHaveBeenCalledWith({ owner: "Орлов И." });
  });

  it("кэш менеджеров общий: вторая карточка видит список без второго fetch (FIX-1)", async () => {
    const { fetchLeadManagers } = await import("@/lib/api");
    const before = (fetchLeadManagers as ReturnType<typeof vi.fn>).mock.calls.length;
    render(
      <>
        <DealCard deal={deal} onUpdate={vi.fn()} />
        <DealCard deal={{ ...deal, id: "2", number: "CRM-2" }} onUpdate={vi.fn()} />
      </>,
    );
    const [menuA, menuB] = screen.getAllByRole("button", { name: "Меню карточки" });
    const boxA = menuA.closest("[data-card-menu]") as HTMLElement;
    const boxB = menuB.closest("[data-card-menu]") as HTMLElement;
    // Карточка A: открыть меню → «Ответственный» → список загрузился (fetch, кэш заполнен)
    fireEvent.click(menuA);
    fireEvent.click(within(boxA).getByRole("button", { name: "Ответственный" }));
    await within(boxA).findByRole("button", { name: /Орлов И\./ });
    // Карточка B смонтирована ДО загрузки кэша (useState(null) на mount): её меню обязано
    // показать менеджеров из кэша, а не вечную «Загрузку…», и БЕЗ второго fetch.
    fireEvent.click(menuB);
    fireEvent.click(within(boxB).getByRole("button", { name: "Ответственный" }));
    expect(await within(boxB).findByRole("button", { name: /Орлов И\./ })).toBeInTheDocument();
    expect(within(boxB).queryByText("Загрузка…")).toBeNull();
    // ≤1: модульный кэш мог прогреть предыдущий тест файла; ключевое — B не делает второй fetch.
    expect((fetchLeadManagers as ReturnType<typeof vi.fn>).mock.calls.length - before).toBeLessThanOrEqual(1);
  });

  it("без onUpdate меню не рендерится (декоративная иконка ⋯)", () => {
    render(<DealCard deal={deal} />);
    expect(screen.queryByRole("button", { name: "Меню карточки" })).toBeNull();
  });

  it("ведёт ссылкой на карточку сделки", () => {
    render(<DealCard deal={deal} />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/crm/deals/1");
  });

  it("onCall открывает обработчик и не вложен в ссылку", () => {
    const onCall = vi.fn();
    render(<DealCard deal={deal} onCall={onCall} />);
    const btn = screen.getByRole("button", { name: "Позвонить" });
    expect(btn.closest("a")).toBeNull();
    btn.click();
    expect(onCall).toHaveBeenCalledTimes(1);
  });
});
