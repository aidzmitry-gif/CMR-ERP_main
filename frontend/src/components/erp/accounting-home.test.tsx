import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { AccountingHome } from "./accounting-home";

it("keeps unavailable document status distinct from zero and requires a book", () => {
  const { rerender } = render(<AccountingHome selected={false} pending={null} onOpen={vi.fn()} />);
  expect(screen.getByRole("button", { name: "Открыть: Документы и ошибки проведения" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Открыть: Политика и доступ" })).toBeEnabled();
  rerender(<AccountingHome selected pending={null} onOpen={vi.fn()} />);
  expect(screen.getByText(/Состояние документов пока не получено/)).toBeInTheDocument();
  expect(screen.queryByText(/включительно: 0/)).not.toBeInTheDocument();
});

it("expense entrypoint requires a book and opens the shared destination", () => {
  const open = vi.fn(); const view = render(<AccountingHome selected={false} pending={null} onOpen={open} />);
  expect(screen.getByRole("button", {name:"Открыть: Контроль расходов"})).toBeDisabled();
  view.rerender(<AccountingHome selected pending={null} onOpen={open} />);
  fireEvent.click(screen.getByRole("button", {name:"Открыть: Контроль расходов"}));
  expect(open).toHaveBeenCalledWith("expenses");
});

it("exposes reviewed payroll entries without treating them as statutory reporting", () => {
  const open = vi.fn();
  render(<AccountingHome selected pending={null} onOpen={open} />);
  fireEvent.click(screen.getByRole("button", { name: "Открыть: Начисления зарплаты" }));
  expect(open).toHaveBeenCalledWith("payroll-accruals");
  expect(screen.getByText(/нормативная сертификация и обязательная отчётность не выполняются/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Открыть: Удержания и взносы" }));
  expect(open).toHaveBeenCalledWith("payroll-statutory");
});

it("opens the core accountant entry points through existing destinations", () => {
  const open = vi.fn();
  render(<AccountingHome selected pending={3} onOpen={open} />);

  for (const title of [
    "План счетов",
    "Документы и ошибки проведения",
    "Журнал операций, ОСВ и анализ счёта",
    "Закрытие месяца",
  ]) {
    expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
  }

  fireEvent.click(screen.getByRole("button", { name: "Открыть: План счетов" }));
  fireEvent.click(screen.getByRole("button", { name: "Открыть: Документы и ошибки проведения" }));
  fireEvent.click(screen.getByRole("button", { name: "Открыть: Журнал операций, ОСВ и анализ счёта" }));
  fireEvent.click(screen.getByRole("button", { name: "Открыть: Закрытие месяца" }));

  expect(open.mock.calls).toEqual([["accounts"], ["inbox"], ["reports"], ["periods"]]);
});
