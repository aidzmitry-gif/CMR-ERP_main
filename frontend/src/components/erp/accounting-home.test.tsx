import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { AccountingHome } from "./accounting-home";

it("keeps unavailable document status distinct from zero and requires a book", () => {
  const { rerender } = render(<AccountingHome selected={false} pending={null} onOpen={vi.fn()} />);
  expect(screen.getByRole("button", { name: "Открыть: Документы и ошибки проведения" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Открыть: План счетов" })).toBeDisabled();
  rerender(<AccountingHome selected pending={null} onOpen={vi.fn()} />);
  expect(screen.getByText(/Состояние документов пока не получено/)).toBeInTheDocument();
  expect(screen.queryByText(/включительно: 0/)).not.toBeInTheDocument();
});

it("renders exactly six main entry points and opens existing destinations", () => {
  const open = vi.fn();
  render(<AccountingHome selected pending={3} onOpen={open} />);

  const titles = [
    "План счетов",
    "Документы и ошибки проведения",
    "Журнал операций, ОСВ и анализ счёта",
    "Закрытие месяца",
    "Контроль расходов",
    "Банк и выписки",
  ];
  expect(screen.getAllByRole("button", { name: /^Открыть:/ })).toHaveLength(6);
  for (const title of titles) {
    expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
  }
  expect(screen.queryByRole("heading", { name: "Продажа товаров" })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Открыть: План счетов" }));
  fireEvent.click(screen.getByRole("button", { name: "Открыть: Документы и ошибки проведения" }));
  fireEvent.click(screen.getByRole("button", { name: "Открыть: Журнал операций, ОСВ и анализ счёта" }));
  fireEvent.click(screen.getByRole("button", { name: "Открыть: Закрытие месяца" }));
  fireEvent.click(screen.getByRole("button", { name: "Открыть: Контроль расходов" }));
  fireEvent.click(screen.getByRole("button", { name: "Открыть: Банк и выписки" }));

  expect(open.mock.calls).toEqual([["accounts"], ["inbox"], ["reports"], ["periods"], ["expenses"], ["bank"]]);
});
