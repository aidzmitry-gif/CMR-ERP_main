import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { AccountingPurchase } from "./accounting-purchase";

it("sends a book's new incoming invoices to the procurement document register", () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  render(<AccountingPurchase org="7" />);
  expect(screen.getByRole("link", { name: "Открыть накладные в закупках" }))
    .toHaveAttribute("href", "/erp/procurement/receipts?org=7");
  expect(screen.queryByRole("button", { name: /Рассчитать поступление|Подтвердить поступление/ })).not.toBeInTheDocument();
  expect(fetcher).not.toHaveBeenCalled();
  vi.unstubAllGlobals();
});
