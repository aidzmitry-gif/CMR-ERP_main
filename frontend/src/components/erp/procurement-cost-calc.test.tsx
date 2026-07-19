import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProcurementCostCalc } from "@/components/erp/procurement-cost-calc";

// Компонент полностью автономный (демо-данные внутри, useState), внешних API/next нет —
// мокать нечего. Тестируем реальный рендер, ветки состояний и взаимодействия.

// В каждой строке таблицы ровно одна кнопка удаления ✕ → надёжный счётчик строк.
const delButtons = () => screen.getAllByRole("button", { name: "✕" });
const rowCount = () => delButtons().length;
const rowTr = (i: number) => delButtons()[i].closest("tr") as HTMLElement;

describe("ProcurementCostCalc", () => {
  it("рендерит заголовок, баннер назначения и сводные карточки", () => {
    render(<ProcurementCostCalc />);
    expect(
      screen.getByText("Предварительная себестоимость (Китай) → цена реализации"),
    ).toBeInTheDocument();
    // баннер про заложенный буфер курса (защита денег)
    expect(screen.getByText(/Буфер курса \+10%/)).toBeInTheDocument();
    // подписи сводных карточек (некоторые дублируются в расшифровке → getAllByText)
    for (const card of ["Себестоимость партии", "Выручка с НДС", "Рентабельность"]) {
      expect(screen.getAllByText(card).length).toBeGreaterThan(0);
    }
  });

  it("рендерит 5 демо-позиций и расшифровку первой строки по умолчанию", () => {
    render(<ProcurementCostCalc />);
    expect(rowCount()).toBe(5);
    // sel=0 → панель расшифровки показывает имя первой номенклатуры (как текст, не value input)
    expect(screen.getByText("Расшифровка расчёта")).toBeInTheDocument();
    expect(screen.getByText(/Аккумулятор Li INR18650-35E 3500mah/)).toBeInTheDocument();
    // разбор landed cost присутствует
    expect(screen.getByText("Комиссия")).toBeInTheDocument();
    expect(screen.getByText(/Landed cost/)).toBeInTheDocument();
  });

  it("клик по другой строке переключает расшифровку на её номенклатуру", () => {
    render(<ProcurementCostCalc />);
    // до клика имени второй позиции в разборе нет
    expect(screen.queryByText(/Lifepo4 battery pack 25.6V\/200Ah/)).not.toBeInTheDocument();
    fireEvent.click(rowTr(1)); // выбор второй строки → setSel(1)
    expect(screen.getByText(/Lifepo4 battery pack 25.6V\/200Ah/)).toBeInTheDocument();
  });

  it("«+ Позиция» добавляет строку", () => {
    render(<ProcurementCostCalc />);
    expect(rowCount()).toBe(5);
    fireEvent.click(screen.getByRole("button", { name: "+ Позиция" }));
    expect(rowCount()).toBe(6);
  });

  it("кнопка удаления ✕ убирает строку", () => {
    render(<ProcurementCostCalc />);
    expect(rowCount()).toBe(5);
    fireEvent.click(delButtons()[0]);
    expect(rowCount()).toBe(4);
  });

  it("«Сбросить» возвращает демо-данные после добавления строки", () => {
    render(<ProcurementCostCalc />);
    fireEvent.click(screen.getByRole("button", { name: "+ Позиция" }));
    expect(rowCount()).toBe(6);
    fireEvent.click(screen.getByRole("button", { name: "Сбросить" }));
    expect(rowCount()).toBe(5);
  });

  it("буфер курса не опускается ниже минимума 10% (защита денег)", () => {
    render(<ProcurementCostCalc />);
    const label = screen.getByText(/Буфер курса, %/).closest("label") as HTMLElement;
    const input = within(label).getByRole("spinbutton") as HTMLInputElement;
    expect(input.value).toBe("10");
    // попытка задать 3% → Math.max(v, 10) удерживает 10
    fireEvent.change(input, { target: { value: "3" } });
    expect(input.value).toBe("10");
  });

  it("снижение наценки ниже стандарта помечает строку индикатором ▼", () => {
    render(<ProcurementCostCalc />);
    // изначально все markup == markup0 → предупреждающего ▼ нет
    expect(screen.queryByText("▼")).not.toBeInTheDocument();

    // ячейка наценки первой строки — input со step=0.05; опускаем 2.0 → 1.5
    const markupInput = within(rowTr(0))
      .getAllByRole("spinbutton")
      .find((el) => el.getAttribute("step") === "0.05") as HTMLInputElement;
    expect(markupInput.value).toBe("2");
    fireEvent.change(markupInput, { target: { value: "1.5" } });

    // индикатор «ниже стандарта» появился и в таблице, и в расшифровке (sel=0)
    expect(screen.getAllByText("▼").length).toBeGreaterThan(0);
    expect(screen.getByText(/× наценка ▼ ниже стандарта/)).toBeInTheDocument();
  });
});
