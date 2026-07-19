import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WorktimeView } from "@/components/erp/worktime-view";

describe("WorktimeView", () => {
  it("по умолчанию открыта вкладка «Мой день» — таймер смены и скорборд выработки", () => {
    render(<WorktimeView />);
    expect(screen.getByText("Текущая смена")).toBeInTheDocument();
    expect(screen.getByText("Моя выработка")).toBeInTheDocument();
    // напоминание про закрытие смены
    expect(screen.getByText(/Не забудьте завершить смену до 18:00/)).toBeInTheDocument();
  });

  it("кнопка «Завершить день» переводит смену в завершённое состояние", () => {
    render(<WorktimeView />);
    const end = screen.getByRole("button", { name: "Завершить день" });
    fireEvent.click(end);
    expect(screen.getByText("День завершён")).toBeInTheDocument();
    expect(screen.getByText(/смена завершена/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Завершить день" })).not.toBeInTheDocument();
  });

  it("скорборд переключает период — заголовок «Отработано» и план меняются", () => {
    render(<WorktimeView />);
    // по умолчанию период «Месяц»: факт «Отработано» 142 ч
    expect(screen.getByText("142")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "День" }));
    // подпись периода сменилась на дневную
    expect(screen.getByText(/сегодня, 02 июля/)).toBeInTheDocument();
    // месячный факт «142» больше не на экране (данные пересчитались под день)
    expect(screen.queryByText("142")).not.toBeInTheDocument();
  });

  it("вкладка «Кто онлайн» показывает счётчик 9 / 12 и таблицу сотрудников", () => {
    render(<WorktimeView />);
    fireEvent.click(screen.getByRole("button", { name: "Кто онлайн" }));
    expect(screen.getByText("9 / 12 онлайн")).toBeInTheDocument();
    expect(screen.getByText("Харькович Д.С.")).toBeInTheDocument();
    // офлайн-сотрудник без часов показан прочерком (Петров С.Г., 0 ч)
    expect(screen.getByText("Петров С.Г.")).toBeInTheDocument();
  });

  it("фильтр по отделу «Продажи» оставляет только менеджеров продаж", () => {
    render(<WorktimeView />);
    fireEvent.click(screen.getByRole("button", { name: "Кто онлайн" }));
    // в отделе есть кнопка-фильтр и позиция в таблице — берём именно кнопку фильтра
    fireEvent.click(screen.getByRole("button", { name: "Продажи" }));
    expect(screen.getByText("Шляхтина А.В.")).toBeInTheDocument();
    expect(screen.getByText("Рязанов К.И.")).toBeInTheDocument();
    expect(screen.getByText("Сидорова М.К.")).toBeInTheDocument();
    // сотрудник другого отдела исчез из таблицы
    expect(screen.queryByText("Козлов А.М.")).not.toBeInTheDocument();
  });

  it("вкладка «Табель» рендерит заголовок и легенду кодов", () => {
    render(<WorktimeView />);
    fireEvent.click(screen.getByRole("button", { name: "Табель (T-13)" }));
    expect(screen.getByText("Табель рабочего времени — Июль 2026")).toBeInTheDocument();
    // легенда кодов невыхода
    expect(screen.getByText(/Больничный/)).toBeInTheDocument();
    // кнопка экспорта пока заглушена
    expect(screen.getByRole("button", { name: "Экспорт T-13" })).toBeDisabled();
  });

  it("клик по ячейке-переработке открывает модалку согласования с фактом > нормы", () => {
    render(<WorktimeView />);
    fireEvent.click(screen.getByRole("button", { name: "Табель (T-13)" }));
    const overtimeCells = screen.getAllByTitle(/Переработка/);
    expect(overtimeCells.length).toBeGreaterThan(0);
    fireEvent.click(overtimeCells[0]);

    expect(screen.getByText("Согласование переработки")).toBeInTheDocument();
    const modal = screen.getByText("Согласование переработки").closest("div") as HTMLElement;
    // первая переработка в порядке DOM — Харькович Д.С., 9 ч при норме 8 → +1 ч
    expect(within(modal).getByText("Харькович Д.С.")).toBeInTheDocument();
    expect(within(modal).getByText("8 ч")).toBeInTheDocument();
    expect(within(modal).getByText("9 ч")).toBeInTheDocument();
    expect(within(modal).getByText("+1 ч")).toBeInTheDocument();
  });

  it("«Согласовать» закрывает модалку и красит ячейку в зелёный (approved)", () => {
    render(<WorktimeView />);
    fireEvent.click(screen.getByRole("button", { name: "Табель (T-13)" }));
    const cell = screen.getAllByTitle(/Переработка/)[0];
    fireEvent.click(cell);
    fireEvent.click(screen.getByRole("button", { name: "Согласовать" }));
    // модалка закрылась
    expect(screen.queryByText("Согласование переработки")).not.toBeInTheDocument();
    // ячейка переработки теперь помечена согласованной (emerald), не янтарной
    expect(cell.className).toMatch(/emerald/);
    expect(cell.className).not.toMatch(/amber/);
  });

  it("«Отклонить» закрывает модалку и зачёркивает ячейку (rejected)", () => {
    render(<WorktimeView />);
    fireEvent.click(screen.getByRole("button", { name: "Табель (T-13)" }));
    const cell = screen.getAllByTitle(/Переработка/)[0];
    fireEvent.click(cell);
    fireEvent.click(screen.getByRole("button", { name: "Отклонить" }));
    expect(screen.queryByText("Согласование переработки")).not.toBeInTheDocument();
    expect(cell.className).toMatch(/line-through/);
  });

  it("клик по фону модалки (не по карточке) закрывает её без решения", () => {
    render(<WorktimeView />);
    fireEvent.click(screen.getByRole("button", { name: "Табель (T-13)" }));
    const cell = screen.getAllByTitle(/Переработка/)[0];
    fireEvent.click(cell);
    // фон-оверлей закрывает по onClick; карточка внутри — stopPropagation
    const title = screen.getByText("Согласование переработки");
    const overlay = title.closest("div")?.parentElement as HTMLElement;
    fireEvent.click(overlay);
    expect(screen.queryByText("Согласование переработки")).not.toBeInTheDocument();
    // ячейка осталась неразрешённой — янтарной
    expect(cell.className).toMatch(/amber/);
  });
});
