import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { AccountingAccountActivity, type AccountMovement } from "./accounting-account-activity";

it("isolates account, currency and exact analytics without relying on object key order", () => {
  const onEntry = vi.fn();
  const base: AccountMovement = { entry_id: 1, line_id: 1, source: "Correct", date: "2026-09-01", account: "60", currency: "USD", side: "credit", amount: "30.00", dimensions: { contract: "A", counterparty: "1" } };
  const movements = [base, { ...base, line_id: 2, source: "Other currency", currency: "EUR" }, { ...base, line_id: 3, source: "Other contract", dimensions: { contract: "B", counterparty: "1" } }, { ...base, line_id: 4, source: "Extra dimension", dimensions: { ...base.dimensions, order: "2" } }, { ...base, line_id: 5, source: "Other account", account: "62" }];
  render(<AccountingAccountActivity row={{ account: "60", title: "Suppliers", currency: "USD", dimensions: { counterparty: "1", contract: "A" }, opening: "0.00", debit: "0.00", credit: "30.00", closing: "-30.00" }} movements={movements} openingMovements={[{ ...base, source: "Opening correct", line_id: 6 }, { ...base, source: "Opening other currency", currency: "EUR", line_id: 7 }]} onEntry={onEntry} onClose={vi.fn()} />);
  fireEvent.click(screen.getByText("№ 1 · Correct"));
  expect(onEntry).toHaveBeenCalledWith(1);
  fireEvent.click(screen.getByText("Проводки начального сальдо"));
  expect(screen.getByText("№ 1 · Opening correct")).toBeInTheDocument();
  expect(screen.queryByText("№ 1 · Opening other currency")).not.toBeInTheDocument();
  for (const name of ["Other currency", "Other contract", "Extra dimension", "Other account"]) expect(screen.queryByText(`№ 1 · ${name}`)).not.toBeInTheDocument();
});
