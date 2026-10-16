import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const currency = vi.hoisted(() => ({
  company: { id: "by", name: "Belarus Office", flag: "BY", base: "BYN" },
  companies: [
    { id: "by", name: "Belarus Office", flag: "BY", base: "BYN" },
    { id: "ru", name: "Russia Office", flag: "RU", base: "RUB" },
    { id: "pl", name: "Poland Office", flag: "PL", base: "EUR" },
  ],
  setCompany: vi.fn(),
}));

vi.mock("@/components/kanban/currency-context", () => ({
  useCurrency: () => currency,
}));

import { CompanySwitcher } from "@/components/kanban/company-switcher";

describe("CompanySwitcher", () => {
  beforeEach(() => {
    currency.setCompany.mockReset();
  });

  it("opens the available display currencies", () => {
    render(<CompanySwitcher />);

    fireEvent.click(screen.getByRole("button", { name: "Валюта сумм: BYN" }));

    for (const code of ["BYN", "RUB", "EUR"]) {
      expect(screen.getByRole("button", { name: code })).toBeInTheDocument();
    }
  });

  it("selects a display currency and closes the list", () => {
    render(<CompanySwitcher />);
    fireEvent.click(screen.getByRole("button", { name: "Валюта сумм: BYN" }));
    fireEvent.click(screen.getByRole("button", { name: "RUB" }));

    expect(currency.setCompany).toHaveBeenCalledWith("ru");
    expect(screen.queryByRole("button", { name: "EUR" })).not.toBeInTheDocument();
  });

  it("does not present demo companies or promise separate accounting", () => {
    const { container } = render(<CompanySwitcher />);
    fireEvent.click(screen.getByRole("button", { name: "Валюта сумм: BYN" }));
    expect(container.textContent).not.toMatch(/Office|юр.?лиц|раздельный учёт|права|demo/i);
    expect(screen.queryByTitle(/раздельного учёта/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /скрыть/i })).not.toBeInTheDocument();
    expect(screen.getByText(/Суммы пересчитаны из BYN по курсу НБ РБ/)).toBeInTheDocument();
  });

  it("closes without changing the selected currency", () => {
    render(<CompanySwitcher />);
    fireEvent.click(screen.getByRole("button", { name: "Валюта сумм: BYN" }));
    fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    expect(screen.queryByRole("button", { name: "EUR" })).not.toBeInTheDocument();
    expect(currency.setCompany).not.toHaveBeenCalled();
  });
});
