import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingProductionCostReview, type CostSource } from "./accounting-production-cost-review";
afterEach(() => vi.unstubAllGlobals());
const source: CostSource = { digest: "a".repeat(64), snapshot: { organization_id: 1, month: "2026-10", policy_id: 2, basis: "direct_cost",
  settings: { wip_account: "20", overhead_accounts: ["25"], order_dimension: "order" }, lines: [
    { line_id: 1, entry_id: 1, source: "materials", account: "20", side: "debit", amount_byn: "10.00", dimensions: { order: "A" }, posting_date: "2026-10-02", opening: false },
    { line_id: 2, entry_id: 2, source: "overhead", account: "25", side: "debit", amount_byn: "1.01", dimensions: {}, posting_date: "2026-10-02", opening: false }] } };
it.each([undefined, 9])("allows fully excluded costs only in correction mode: %s", async correctionOf => {
  const onPrepared = vi.fn();
  const request = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => Response.json({ digest: "b".repeat(64),
    snapshot: { organization_id: 1, month: "2026-10", status: "reviewed_allocation_preview", posted: false,
      review: JSON.parse(String(init?.body)), allocations: [] } }));
  vi.stubGlobal("fetch", request);
  render(<AccountingProductionCostReview source={source} disabled={false} onPrepared={onPrepared} correctionOf={correctionOf} />);
  const calculate = screen.getByText("Рассчитать распределение по проверенным строкам");
  for (const id of [1, 2]) {
    fireEvent.change(screen.getByLabelText(`Назначение строки ${id}`), { target: { value: "excluded" } });
    expect(calculate).toBeDisabled();
    fireEvent.change(screen.getByLabelText(`Основание строки ${id}`), { target: { value: "Исправлены первичные основания" } });
  }
  expect(request).not.toHaveBeenCalled();
  if (!correctionOf) { expect(calculate).toBeDisabled(); return; }
  expect(calculate).not.toBeDisabled();
  fireEvent.click(calculate);
  expect(await screen.findByRole("status")).toHaveTextContent("Целевое распределение равно нулю");
  expect(request).toHaveBeenCalledTimes(1);
  expect(String(request.mock.calls[0][0])).toMatch(/correction-review\?original_entry_id=9$/);
  expect(onPrepared).toHaveBeenLastCalledWith(expect.objectContaining({ earliestDate: "2026-10-01",
    review: expect.objectContaining({ orders: [] }) }));
  fireEvent.change(screen.getByLabelText("Назначение строки 1"), { target: { value: "direct_cost" } });
  expect(calculate).toBeDisabled();
  expect(onPrepared).toHaveBeenLastCalledWith(null);
});
it.each([false, true])("requires explicit bindings and an unchanged review echo; forged echo: %s", async forged => {
  const onPrepared = vi.fn();
  const request = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (String(url).endsWith("/orders")) return Response.json([{ id: 7, number: "PR-7", product: "Product" }]);
    const command = JSON.parse(String(init?.body));
    if (forged) command.classifications[0].evidence = "Другое основание затрат";
    return Response.json({ digest: "b".repeat(64), snapshot: { organization_id: 1, month: "2026-10", status: "reviewed_allocation_preview", posted: false,
      review: command, allocations: [{ account: "25", pool_dimensions: {}, allocation: { amount_byn: "1.01", shares: [{ order_id: 7, basis_amount: "10.000000", amount_byn: "1.01" }] } }] } });
  });
  vi.stubGlobal("fetch", request);
  render(<AccountingProductionCostReview source={source} disabled={false} onPrepared={onPrepared} />);
  const calculate = screen.getByText("Рассчитать распределение по проверенным строкам");
  expect(calculate).toBeDisabled(); expect(request).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Загрузить производственные наряды"));
  await waitFor(() => expect(screen.getByText("Загрузить производственные наряды")).not.toBeDisabled());
  fireEvent.change(screen.getByLabelText("Назначение строки 1"), { target: { value: "direct_cost" } });
  fireEvent.change(screen.getByLabelText("Назначение строки 2"), { target: { value: "overhead" } });
  for (const id of [1, 2]) fireEvent.change(screen.getByLabelText(`Основание строки ${id}`), { target: { value: "Проверено по документам" } });
  expect(calculate).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Наряд для заказа A"), { target: { value: "7" } });
  fireEvent.change(screen.getByLabelText("Основание связи заказа A"), { target: { value: "Проверенная связь с нарядом" } });
  fireEvent.click(calculate);
  if (forged) {
    expect(await screen.findByRole("alert")).toHaveTextContent("не соответствует");
    expect(screen.queryByRole("status")).toBeNull();
    expect(onPrepared.mock.calls.every(([value]) => value === null)).toBe(true);
    return;
  }
  expect(await screen.findByRole("status")).toHaveTextContent("распределено 1.01 BYN");
  const posts = request.mock.calls.filter(([, init]) => init?.method === "POST");
  expect(posts).toHaveLength(1);
  expect(String(posts[0][0])).toMatch(/production-cost-review$/);
  expect(JSON.parse(String(posts[0][1]?.body)).orders).toEqual([{ analytical_order: "A", order_id: 7, evidence: "Проверенная связь с нарядом" }]);
  expect(onPrepared).toHaveBeenLastCalledWith({ digest: "b".repeat(64), earliestDate: "2026-10-02", review: JSON.parse(String(posts[0][1]?.body)) });
  fireEvent.change(screen.getByLabelText("Основание строки 1"), { target: { value: "Изменённое основание" } });
  expect(screen.queryByRole("status")).toBeNull();
  expect(onPrepared).toHaveBeenLastCalledWith(null);
});
