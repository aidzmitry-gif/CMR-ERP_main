import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AccountingProductionMaterialCost } from "./accounting-production-material-cost";

afterEach(() => vi.unstubAllGlobals());

const result = {
  organization_id: 1, month: "2026-10", policy_id: 2, scope: "production_material_cost_basis",
  status: "reviewed_material_cost", explanation: "Списание сверено с WMS и партией.", posting_available: false,
  final_cost_certified: false,
  wms_movement: { id: 9, reason: "production_issue", sku: "MAT-1", warehouse: "Main", lot: "LOT-1", quantity: "2.000000", doc_ref: "PROD-42" },
  inventory_cost: { issue_cost_byn: "12.50", account: "10.1", basis_digest: "a".repeat(64) },
  candidate_posting: {
    debit: { account: "20", amount_byn: "12.50", dimensions: { department: "SHOP", order: "A" } },
    credit: { account: "10.1", amount_byn: "12.50", quantity: "2.000000", dimensions: { warehouse: "Main", sku: "MAT-1", lot: "LOT-1" } },
  },
};

function fill() {
  const values: Record<string, string> = {
    "Наряд для материала": "42", "Аналитика наряда": "A", "Подразделение материала": "SHOP",
    "WMS движение материала": "9", "SKU материала": "MAT-1", "Партия материала": "LOT-1", "Количество материала": "2.00",
  };
  for (const [label, value] of Object.entries(values)) fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

it("shows the exact debit/credit candidate for a production issue", async () => {
  const request = vi.fn(async () => Response.json(result));
  vi.stubGlobal("fetch", request);
  const onEntry = vi.fn();
  render(<AccountingProductionMaterialCost org="1" month="2026-10" policyId="2" disabled={false} onEntry={onEntry} />);
  fill();
  fireEvent.click(screen.getByText("Проверить материал и НЗП"));
  await screen.findByText(/Дт 20 12.50 BYN/);
  expect(String(request.mock.calls[0][0])).toContain("production-material-issue-preview");
  expect(screen.getByText(/партия LOT-1/)).toBeVisible();
  expect(screen.getByText(/Проводка не создана/)).toBeVisible();
  expect(onEntry).not.toHaveBeenCalled();
});

it("rejects a forged response scope or non-production movement", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ ...result, scope: "wrong", wms_movement: { ...result.wms_movement, reason: "pick" } })));
  render(<AccountingProductionMaterialCost org="1" month="2026-10" policyId="2" disabled={false} />);
  fill();
  fireEvent.click(screen.getByText("Проверить материал и НЗП"));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("не соответствует"));
});

it("prepares and confirms the reviewed material package, then opens the immutable entry", async () => {
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", { getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) });
  const posted = { organization_id: 1, month: "2026-10", policy_id: 2, scope: "production_material_cost_basis",
    status: "reviewed_material_cost", explanation: "Списание сверено с WMS и партией.", posting_available: true,
    final_cost_certified: false, basis_digest: "a".repeat(64), digest: "b".repeat(64),
    posting: { lines: [{ side: "debit", account: "20", amount: "12.50" }, { side: "credit", account: "10.1", amount: "12.50" }] } };
  const receipt = { organization_id: 1, month: "2026-10", actor: "chief", order_id: 42, wms_movement_id: 9,
    policy_id: 2, basis_digest: posted.basis_digest, digest: posted.digest, entry_id: 91,
    entry: { id: 91 }, posted: true, final_cost_certified: false };
  const request = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = String(url);
    if (path.endsWith("production-material-issue-preview")) return Response.json(result);
    if (path.endsWith("production-material-issue-posting-preview")) return Response.json(posted);
    if (path.endsWith("production-overhead-access")) return Response.json({ organization_id: 1, principal: "chief", can_confirm: true });
    if (path.endsWith("production-material-issue-posting-status/9")) return request.mock.calls.some(([url]) => String(url).includes("production-material-issue-confirm"))
      ? Response.json(receipt) : new Response("{}", { status: 404 });
    if (path.endsWith("production-material-issue-confirm") && init?.method === "POST") return new Response("{}", { status: 201 });
    throw new Error(`Unexpected request ${path}`);
  });
  vi.stubGlobal("fetch", request);
  const onEntry = vi.fn();
  render(<AccountingProductionMaterialCost org="1" month="2026-10" policyId="2" disabled={false} onEntry={onEntry} />);
  fill(); fireEvent.click(screen.getByText("Проверить материал и НЗП"));
  await screen.findByText(/Проводка не создана/);
  fireEvent.click(screen.getByText("Подготовить подтверждение проводки"));
  await screen.findByText(/Пакет проводки подготовлен/);
  fireEvent.click(screen.getByText("Провести проверенный материал"));
  await screen.findByText(/Материал проведён. Проводка №91/);
  expect(onEntry).toHaveBeenCalledWith(91);
  expect(request.mock.calls.filter(([url]) => String(url).includes("production-material-issue-confirm")).length).toBe(1);
});
