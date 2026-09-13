import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { AccountingHome } from "./accounting-home";

it("keeps unavailable document status distinct from zero and requires a book", () => {
  const { rerender } = render(<AccountingHome selected={false} pending={null} onOpen={vi.fn()} />);
  expect(screen.getByRole("button", { name: "Открыть: Документы к проведению" })).toBeDisabled();
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

it("exposes the verified gross payroll import without calling it statutory payroll", () => {
  const open = vi.fn();
  render(<AccountingHome selected pending={null} onOpen={open} />);
  fireEvent.click(screen.getByRole("button", { name: "Открыть: Начисления зарплаты" }));
  expect(open).toHaveBeenCalledWith("payroll-accruals");
  expect(screen.getByText(/нормативная сертификация и обязательная отчётность не выполняются/)).toBeInTheDocument();
});

it("exposes reviewed payroll deductions and contributions as a separate workspace", () => {
  const open = vi.fn();
  render(<AccountingHome selected pending={null} onOpen={open} />);
  fireEvent.click(screen.getByRole("button", { name: "Открыть: Удержания и взносы" }));
  expect(open).toHaveBeenCalledWith("payroll-statutory");
  expect(screen.getByText(/ставки и расчёт от оклада не угадываются/)).toBeInTheDocument();
});
