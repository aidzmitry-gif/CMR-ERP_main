import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AccountingLateCostPreview } from "./accounting-late-cost-preview";

const fetchMock = vi.fn();
const policy = { id: 2, effective_from: "2026-09-01", reference: "Policy", late_cost_allocation: { basis: "quantity", rounding: "largest_remainder_cent" } };
const result = () => ({ organization_id: 1, expense_id: 7, source_version: 3, policy_id: 2, basis_digest: "a".repeat(64),
  posted: false, confirmation_available: false, normative_verified: false,
  shares: [{ receipt_id: 4, version: 1, line_number: 1, destination: "remaining", quantity: "6.000000", amount_byn: "60.00" },
    { receipt_id: 4, version: 1, line_number: 1, destination: "disposed", quantity: "4.000000", amount_byn: "40.00" }] });
beforeEach(() => { vi.stubGlobal("fetch", fetchMock); });
afterEach(() => { vi.unstubAllGlobals(); vi.resetAllMocks(); });
function setup(value: unknown = result(), policies: unknown[] = [policy], currency?: string) {
  fetchMock.mockImplementation((_url, options) => Promise.resolve({ ok: true, json: async () => options?.method === "POST" ? value : policies }));
  render(<AccountingLateCostPreview org="1" expenseId={7} version={3} initialDate="2026-09-11" disabled={false} currency={currency} />);
}
async function fill() {
  await screen.findByText(/Политика: Policy/);
  fireEvent.change(screen.getByLabelText("Включить в стоимость, BYN"), { target: { value: "100.00" } });
  fireEvent.change(screen.getByLabelText("Исключено из стоимости, BYN"), { target: { value: "0.00" } });
  fireEvent.change(screen.getByLabelText("Основание включения и исключения"), { target: { value: "Verified primary classification" } });
}
it("shows exact shares and only sends the saved source version to preview", async () => {
  setup(); await fill(); fireEvent.click(screen.getByRole("button", { name: "Рассчитать распределение" }));
  await screen.findByText("60.00"); expect(screen.getByText("40.00")).toBeInTheDocument();
  expect(screen.getByText("Нормативная применимость политики ещё не подтверждена.")).toBeInTheDocument();
  const writes = fetchMock.mock.calls.filter(([, options]) => options?.method === "POST");
  expect(writes).toHaveLength(1);
  expect(writes[0][0]).toBe("/api/accounting/organizations/1/additional-expenses/7/preview");
  expect(JSON.parse(writes[0][1].body)).toEqual({ expected_version: 3, policy_id: 2, posting_date: "2026-09-11",
    capitalizable_amount_byn: "100.00", excluded_amount_byn: "0.00", classification_evidence: "Verified primary classification" });
  expect(screen.queryByRole("button", { name: /провести/i })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Включить в стоимость, BYN"), { target: { value: "90.00" } });
  fireEvent.change(screen.getByLabelText("Включить в стоимость, BYN"), { target: { value: "100.00" } });
  expect(screen.queryByText("60.00")).not.toBeInTheDocument();
});
it("sends explicit source currency conversion evidence", async () => {
  setup(result(), [policy], "USD"); await fill();
  fireEvent.change(screen.getByLabelText("Курс USD"), { target: { value: "3.2" } });
  fireEvent.change(screen.getByLabelText("Дата курса"), { target: { value: "2026-09-10" } });
  fireEvent.change(screen.getByLabelText("Источник курса"), { target: { value: "Synthetic official rate evidence" } });
  fireEvent.click(screen.getByRole("button", { name: "Рассчитать распределение" }));
  await screen.findByText("60.00");
  const writes = fetchMock.mock.calls.filter(([, options]) => options?.method === "POST");
  expect(JSON.parse(writes[0][1].body).conversion).toEqual({ currency: "USD", rate: "3.2", rate_scale: 1,
    rate_date: "2026-09-10", rate_source: "Synthetic official rate evidence" });
});
it("does not fall back to an earlier configured policy", async () => {
  setup(result(), [policy, { ...policy, id: 3, effective_from: "2026-09-10", late_cost_allocation: null }]);
  await screen.findByText(/не настроено распределение/);
  expect(screen.getByRole("button", { name: "Рассчитать распределение" })).toBeDisabled();
  expect(fetchMock.mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
});
it.each([{ organization_id: 9 }, { source_version: 2 }, { shares: [] },
  { shares: [{ ...result().shares[0], amount_byn: 60 }] }, { shares: [{ ...result().shares[0], version: 0 }] }])(
  "rejects unconfirmed calculation %j", async patch => {
    setup({ ...result(), ...patch }); await fill(); fireEvent.click(screen.getByRole("button", { name: "Рассчитать распределение" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("не подтверждён"));
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

it.each([[result().shares[0]], [result().shares[0], result().shares[0]]])("rejects incomplete or duplicate shares %j", async (...shares) => {
  setup({ ...result(), shares }); await fill(); fireEvent.click(screen.getByRole("button", { name: "Рассчитать распределение" }));
  await screen.findByText(/Доли расчёта не подтверждены/);
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
