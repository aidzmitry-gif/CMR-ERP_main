import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  issueDocument: vi.fn(),
}));

import { DealCard } from "@/components/kanban/deal-card";
import * as api from "@/lib/api";
import type { Deal } from "@/lib/types";

const mockApi = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

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

  // --- Слайс 5 (C): чип первого касания ---

  it("noTouchDays рисует «⏱ без касания N дн» ВМЕСТО «нет шага» (первое касание приоритетнее)", () => {
    const { rerender } = render(
      <DealCard deal={{ ...deal, nextStep: undefined }} noStep noTouchDays={2} />,
    );
    expect(screen.getByText(/без касания 2 дн/)).toBeInTheDocument();
    expect(screen.queryByText("нет шага")).toBeNull();
    rerender(<DealCard deal={{ ...deal, nextStep: undefined }} noStep noTouchDays={0} />);
    expect(screen.getByText(/без касания 0 дн/)).toBeInTheDocument();
  });

  it("noTouchDays=null (по умолчанию) — старый маркер «нет шага» продолжает работать", () => {
    render(<DealCard deal={{ ...deal, nextStep: undefined }} noStep noTouchDays={null} />);
    expect(screen.getByText("нет шага")).toBeInTheDocument();
    expect(screen.queryByText(/без касания/)).toBeNull();
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

  // --- Слайс 4: композер «след. шаг» ---

  it("без onNextStep строка шага остаётся статичным текстом (как раньше), композер не рендерится", () => {
    render(<DealCard deal={{ ...deal, nextStep: undefined }} />);
    expect(screen.getByText("—")).toBeInTheDocument(); // "След. шаг: —" (нет шага, статично)
    expect(screen.queryByText("+ след. шаг")).toBeNull();
  });

  it("onNextStep передан, шага нет → кликабельная заглушка «+ след. шаг»", () => {
    render(<DealCard deal={{ ...deal, nextStep: undefined }} onNextStep={vi.fn()} />);
    expect(screen.getByText("+ след. шаг")).toBeInTheDocument();
  });

  it("клик по строке шага открывает композер с пресетами стадии", () => {
    render(<DealCard deal={{ ...deal, nextStep: undefined }} stageId="qual" onNextStep={vi.fn()} />);
    fireEvent.click(screen.getByText("+ след. шаг"));
    expect(screen.getByText("Отправить КП")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeInTheDocument();
  });

  it("пункт CardMenu «След. шаг…» открывает тот же композер", () => {
    render(
      <DealCard deal={{ ...deal, nextStep: undefined }} stageId="qual" onUpdate={vi.fn()} onNextStep={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Меню карточки" }));
    fireEvent.click(screen.getByRole("button", { name: "След. шаг…" }));
    expect(screen.getByText("Отправить КП")).toBeInTheDocument();
  });

  it("без onNextStep пункт «След. шаг…» в CardMenu не рендерится", () => {
    render(<DealCard deal={deal} onUpdate={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Меню карточки" }));
    expect(screen.queryByRole("button", { name: "След. шаг…" })).toBeNull();
  });

  it("выбор пресета + «Сохранить» зовёт onNextStep с текстом и ISO-датой", () => {
    const onNextStep = vi.fn();
    render(<DealCard deal={{ ...deal, nextStep: undefined }} stageId="qual" onNextStep={onNextStep} />);
    fireEvent.click(screen.getByText("+ след. шаг"));
    fireEvent.click(screen.getByText("Отправить КП"));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(onNextStep).toHaveBeenCalledWith(
      expect.objectContaining({ text: "Отправить КП", atISO: expect.any(String) }),
    );
  });

  it("«Выполнен, без следующего» зовёт onNextStep(null/null)", () => {
    const onNextStep = vi.fn();
    render(<DealCard deal={deal} stageId="qual" onNextStep={onNextStep} />); // deal уже с nextStep="Звонок"
    // Триггер — кнопка «След. шаг: Звонок» (accessible name склеивает вложенный <span>).
    fireEvent.click(screen.getByRole("button", { name: /Звонок/ }));
    fireEvent.click(screen.getByRole("button", { name: "Выполнен, без следующего" }));
    expect(onNextStep).toHaveBeenCalledWith({ text: null, atISO: null });
  });

  // --- Слайс 6: счёт с карточки ---

  it("C: invoiceBadge рендерит бейдж рядом с суммой; без пропа/null — не рендерит", () => {
    const { rerender } = render(
      <DealCard deal={deal} invoiceBadge={{ label: "💳 просрочен", tone: "red" }} />,
    );
    expect(screen.getByText("💳 просрочен")).toBeInTheDocument();
    rerender(<DealCard deal={deal} invoiceBadge={null} />);
    expect(screen.queryByText("💳 просрочен")).toBeNull();
    rerender(<DealCard deal={deal} />);
    expect(screen.queryByText(/просрочен|оплачен|истекает/)).toBeNull();
  });

  it("D: пункт «Выставить счёт» скрыт для закрытой стадии (won/lost)", () => {
    render(<DealCard deal={deal} onUpdate={vi.fn()} stageId="won" />);
    fireEvent.click(screen.getByRole("button", { name: "Меню карточки" }));
    expect(screen.queryByText("💳 Выставить счёт")).toBeNull();
  });

  it("D: пункт «Выставить счёт» виден для открытой стадии", () => {
    render(<DealCard deal={deal} onUpdate={vi.fn()} stageId="qual" />);
    fireEvent.click(screen.getByRole("button", { name: "Меню карточки" }));
    expect(screen.getByText("💳 Выставить счёт")).toBeInTheDocument();
  });

  it("D: клик «Выставить счёт» → issueDocument вызван; ok → onNextStep «Проверить оплату…» + window.open(renderUrl)", async () => {
    vi.stubGlobal("open", vi.fn());
    vi.stubGlobal("alert", vi.fn());
    mockApi(api.issueDocument).mockResolvedValue({
      ok: true,
      message: "✅ Счёт СЧ-1 выставлен",
      renderUrl: "/api/sales/documents/9/render",
    });
    const onNextStep = vi.fn();
    render(<DealCard deal={deal} onUpdate={vi.fn()} onNextStep={onNextStep} stageId="qual" />);
    fireEvent.click(screen.getByRole("button", { name: "Меню карточки" }));
    fireEvent.click(screen.getByText("💳 Выставить счёт"));
    await waitFor(() => expect(api.issueDocument).toHaveBeenCalledWith("1", "invoice"));
    await waitFor(() =>
      expect(onNextStep).toHaveBeenCalledWith(
        expect.objectContaining({
          text: expect.stringContaining("Проверить оплату"),
          atISO: expect.any(String),
        }),
      ),
    );
    expect(window.open).toHaveBeenCalledWith("/api/sales/documents/9/render", "_blank");
    expect(window.alert).toHaveBeenCalledWith("✅ Счёт СЧ-1 выставлен");
  });

  it("D: неуспех (ok=false) — onNextStep НЕ вызван", async () => {
    vi.stubGlobal("open", vi.fn());
    vi.stubGlobal("alert", vi.fn());
    mockApi(api.issueDocument).mockResolvedValue({ ok: false, message: "⚠️ Не удалось выставить счёт" });
    const onNextStep = vi.fn();
    render(<DealCard deal={deal} onUpdate={vi.fn()} onNextStep={onNextStep} stageId="qual" />);
    fireEvent.click(screen.getByRole("button", { name: "Меню карточки" }));
    fireEvent.click(screen.getByText("💳 Выставить счёт"));
    await waitFor(() => expect(api.issueDocument).toHaveBeenCalled());
    expect(onNextStep).not.toHaveBeenCalled();
  });
});
