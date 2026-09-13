import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingProductionOutputCost } from "./accounting-production-output-cost";

afterEach(() => vi.unstubAllGlobals());

const result = { organization_id: 1, month: "2026-10", policy_id: 2, analytical_order: "A", warehouse: "Главный",
  output: { planned_quantity: "2.00", confirmed_quantity: "2.00", accepted_quantity: "2.00", rejected_quantity: "0.00", pending_quantity: "0.00", unit: "шт" },
  wip: { account: "20", balance_byn: "100.00", unit_cost_byn: "50.000000", source_lines: [{ entry_id: 9, line_id: 11, side: "debit", amount_byn: "100.00" }] },
  target: { finished_goods_account: null }, status: "awaiting_finished_goods_policy", explanation: "Счёт не настроен",
  candidate_transfer_byn: "100.00", posting_available: false, final_cost_certified: false, scope: "production_output_cost_basis" };

it("loads a reviewable output basis and drills into the WIP entry", async () => {
  const request = vi.fn(async () => Response.json(result));
  vi.stubGlobal("fetch", request);
  const onEntry = vi.fn();
  render(<AccountingProductionOutputCost org="1" month="2026-10" policyId="2" disabled={false} onEntry={onEntry} />);
  fireEvent.change(screen.getByLabelText("Номер производственного наряда"), { target: { value: "42" } });
  fireEvent.change(screen.getByLabelText("Аналитический заказ"), { target: { value: "A" } });
  fireEvent.click(screen.getByText("Сверить выпуск и НЗП"));
  await screen.findByText(/К переносу: 100.00 BYN/);
  expect(String(request.mock.calls[0][0])).toContain("policy_id=2");
  fireEvent.click(screen.getByText("Проводка №9"));
  expect(onEntry).toHaveBeenCalledWith(9);
});

it("rejects an untrusted response shape", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ ...result, scope: "wrong" })));
  render(<AccountingProductionOutputCost org="1" month="2026-10" policyId="2" disabled={false} />);
  fireEvent.change(screen.getByLabelText("Номер производственного наряда"), { target: { value: "42" } });
  fireEvent.change(screen.getByLabelText("Аналитический заказ"), { target: { value: "A" } });
  fireEvent.click(screen.getByText("Сверить выпуск и НЗП"));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("не соответствует"));
});

it("prepares and confirms a complete output transfer with durable recovery", async () => {
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) });
  const basis = { ...result, basis_digest: "a".repeat(64), status: "ready_for_transfer_review", target: { finished_goods_account: "43" },
    output: { ...result.output, sku_code: "WIDGET", lot: "LOT-1", documents: [{ document_id: 101, operation_date: "2026-10-10" }] } };
  const prepared = { organization_id: 1, month: "2026-10", policy_id: 2, scope: "production_output_cost_basis", posting_available: true, final_cost_certified: false,
    basis_digest: basis.basis_digest, digest: "b".repeat(64), posting: { lines: [{ side: "debit", account: "43", amount: "100.00" }, { side: "credit", account: "20", amount: "100.00" }] } };
  const receipt = { organization_id: 1, month: "2026-10", actor: "chief", order_id: 42, basis_digest: basis.basis_digest,
    digest: prepared.digest, entry_id: 91, entry: { id: 91 }, posted: true, final_cost_certified: false };
  const request = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = String(url);
    if (path.includes("production-output-cost-preview")) return Response.json(basis);
    if (path.includes("production-output-transfer-preview")) return Response.json(prepared);
    if (path.includes("production-overhead-access")) return Response.json({ organization_id: 1, principal: "chief", can_confirm: true });
    if (path.includes("production-output-transfer-status/42")) return request.mock.calls.some(([value]) => String(value).includes("production-output-transfer-confirm")) ? Response.json(receipt) : new Response("{}", { status: 404 });
    if (path.includes("production-output-transfer-confirm") && init?.method === "POST") return new Response("{}", { status: 201 });
    throw new Error(`Unexpected request ${path}`);
  });
  vi.stubGlobal("fetch", request);
  const onEntry = vi.fn();
  render(<AccountingProductionOutputCost org="1" month="2026-10" policyId="2" disabled={false} onEntry={onEntry} />);
  fireEvent.change(screen.getByLabelText("Номер производственного наряда"), { target: { value: "42" } });
  fireEvent.change(screen.getByLabelText("Аналитический заказ"), { target: { value: "A" } });
  fireEvent.change(screen.getByLabelText("Подразделение выпуска"), { target: { value: "SHOP" } });
  fireEvent.click(screen.getByText("Сверить выпуск и НЗП")); await screen.findByText(/Подготовить перенос НЗП/);
  fireEvent.click(screen.getByText("Подготовить перенос НЗП")); await screen.findByText(/Пакет переноса подготовлен/);
  fireEvent.click(screen.getByText("Провести проверенный выпуск")); await screen.findByText(/Выпуск проведён в готовую продукцию/);
  expect(onEntry).toHaveBeenCalledWith(91);
  expect(request.mock.calls.filter(([url]) => String(url).includes("production-output-transfer-confirm")).length).toBe(1);
});
