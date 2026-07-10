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

  it("opens the available company list", () => {
    render(<CompanySwitcher />);

    fireEvent.click(screen.getByRole("button", { name: /Belarus Office/ }));

    expect(screen.getByRole("button", { name: /Russia Office/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Poland Office/ })).toBeInTheDocument();
  });

  it("selects a company and closes the list", () => {
    render(<CompanySwitcher />);
    fireEvent.click(screen.getByRole("button", { name: /Belarus Office/ }));
    fireEvent.click(screen.getByRole("button", { name: /Russia Office/ }));

    expect(currency.setCompany).toHaveBeenCalledWith("ru");
    expect(screen.queryByRole("button", { name: /Poland Office/ })).not.toBeInTheDocument();
  });

  it("keeps the current company visible and prevents hiding it", () => {
    const { container } = render(<CompanySwitcher />);
    fireEvent.click(screen.getByRole("button", { name: /Belarus Office/ }));

    const currentVisibilityButton = container.querySelector("button[disabled]");
    expect(currentVisibilityButton).toBeDisabled();

    const polandButton = screen.getByRole("button", { name: /Poland Office/ });
    const polandVisibilityButton = polandButton.parentElement?.querySelector("button[aria-label]");
    expect(polandVisibilityButton).not.toBeNull();
    fireEvent.click(polandVisibilityButton!);

    expect(screen.getAllByRole("button", { name: /Belarus Office/ })).toHaveLength(2);
    expect(screen.queryByRole("button", { name: /Poland Office/ })).not.toBeInTheDocument();
  });
});
