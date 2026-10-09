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

it.each(["empty-debit", "amount"])("rejects an invalid initial material candidate: %s", async (mismatch) => {
  const invalid = { ...result, candidate_posting: {
    debit: { ...result.candidate_posting.debit }, credit: { ...result.candidate_posting.credit },
  } };
  if (mismatch === "empty-debit") invalid.candidate_posting.debit.account = "";
  else {
    invalid.candidate_posting.debit.amount_byn = "7.00";
    invalid.candidate_posting.credit.amount_byn = "7.00";
  }
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(invalid)));
  render(<AccountingProductionMaterialCost org="1" month="2026-10" policyId="2" disabled={false} />);
  fill(); fireEvent.click(screen.getByText("Проверить материал и НЗП"));
  await screen.findByRole("alert");
  expect(screen.queryByText("Подготовить подтверждение проводки")).not.toBeInTheDocument();
});

it.each([false, true, "zero"])("prepares and confirms the reviewed material package (multiple credits: %s)", async (multiple) => {
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", { getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) });
  const posted = { organization_id: 1, month: "2026-10", policy_id: 2, scope: "production_material_cost_basis",
    status: "reviewed_material_cost", explanation: "Списание сверено с WMS и партией.", posting_available: true,
    final_cost_certified: false, basis_digest: "a".repeat(64), digest: "b".repeat(64),
    inventory_cost: result.inventory_cost, posting_document: { account: "10.1" },
    posting: { lines: [{ side: "debit", account: "20", amount: "12.50" }, { side: "credit", account: "10.1", amount: "12.50" }] } };
  if (multiple === true) posted.posting.lines.splice(1, 1,
    { side: "credit", account: "10.1", amount: "7.00" },
    { side: "credit", account: "10.1", amount: "5.50" });
  const receipt = { organization_id: 1, month: "2026-10", actor: "chief", order_id: 42, wms_movement_id: 9,
    policy_id: 2, basis_digest: posted.basis_digest, digest: posted.digest, entry_id: 91,
    entry: { id: 91 }, posted: true, final_cost_certified: false };
  const zero = multiple === "zero";
  const zeroPreview = { ...result, inventory_cost: { ...result.inventory_cost, issue_cost_byn: "0.00" },
    candidate_posting: { debit: { ...result.candidate_posting.debit, amount_byn: "0.00" },
      credit: { ...result.candidate_posting.credit, amount_byn: "0.00" } } };
  const zeroPrepared = { ...zeroPreview, zero_value: true, quantity_registered: false, entry_id: null,
    basis_digest: "d".repeat(64), digest: posted.digest,
    zero_value_receipt: { command_version: 5, operation: "inventory_issue", basis_digest: "d".repeat(64),
      material_binding: { movement_id: 9, order_id: 42 }, destination_account: "20",
      document: { account: "10.1", warehouse: "Главный", sku: "MAT-1", lot: "LOT-1", quantity: "2.000000" } } };
  const zeroReceipt = { ...receipt, basis_digest: "d".repeat(64), entry_id: null, entry: null, posted: false, zero_value: true,
    quantity_registered: true, receipt_id: 17, receipt_digest: "c".repeat(64) };
  const request = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = String(url);
    if (path.endsWith("production-material-issue-preview")) return Response.json(zero ? zeroPreview : result);
    if (path.endsWith("production-material-issue-posting-preview")) return Response.json(zero ? zeroPrepared : posted);
    if (path.endsWith("production-overhead-access")) return Response.json({ organization_id: 1, principal: "chief", can_confirm: true });
    if (path.endsWith("production-material-issue-posting-status/9")) return request.mock.calls.some(([url]) => String(url).includes("production-material-issue-confirm"))
      ? Response.json(zero ? zeroReceipt : receipt) : new Response("{}", { status: 404 });
    if (path.endsWith("production-material-issue-confirm") && init?.method === "POST") return new Response("{}", { status: 201 });
    throw new Error(`Unexpected request ${path}`);
  });
  vi.stubGlobal("fetch", request);
  const onEntry = vi.fn();
  render(<AccountingProductionMaterialCost org="1" month="2026-10" policyId="2" disabled={false} onEntry={onEntry} />);
  fill(); fireEvent.click(screen.getByText("Проверить материал и НЗП"));
  await screen.findByText(/Проводка не создана/);
  const previewCall = request.mock.calls.find(([url]) => String(url).endsWith("production-material-issue-preview"))!;
  expect(JSON.parse(String(previewCall[1]?.body))).not.toHaveProperty("account");
  expect(screen.queryByLabelText("Счёт материала")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Подготовить подтверждение проводки"));
  await screen.findByText(/Пакет проводки подготовлен/);
  if (multiple === true) {
    expect(screen.getByText("Кт 10.1 · 7.00 BYN")).toBeInTheDocument();
    expect(screen.getByText("Кт 10.1 · 5.50 BYN")).toBeInTheDocument();
  }
  fireEvent.click(screen.getByText("Провести проверенный материал"));
  if (zero) {
    await screen.findByText(/Количество списано в НЗП. Квитанция №17/);
    expect(onEntry).not.toHaveBeenCalled();
    expect(screen.queryByText("Открыть проводку материала")).not.toBeInTheDocument();
    const call = request.mock.calls.find(([url]) => String(url).includes("production-material-issue-confirm"))!;
    expect(JSON.parse(String(call[1]?.body)).zero_value).toBe(true);
    expect(values.size).toBe(0);
  } else {
    await screen.findByText(/Материал проведён. Проводка №91/);
    expect(onEntry).toHaveBeenCalledWith(91);
  }
  expect(request.mock.calls.filter(([url]) => String(url).includes("production-material-issue-confirm")).length).toBe(1);
  const confirmCall = request.mock.calls.find(([url]) => String(url).endsWith("production-material-issue-confirm"))!;
  expect(JSON.parse(String(confirmCall[1]?.body)).account).toBe("10.1");
});

it.each(["cost", "basis", "debit", "empty-debit", "zero"])("rejects preparation that differs from reviewed material: %s", async (mismatch) => {
  const prepared = { ...result, posting_available: true, basis_digest: "a".repeat(64), digest: "b".repeat(64),
    inventory_cost: { ...result.inventory_cost }, posting_document: { account: "10.1" },
    posting: { lines: [{ side: "debit", account: "20", amount: "12.50" }, { side: "credit", account: "10.1", amount: "12.50" }] },
    zero_value: false };
  if (mismatch === "cost") {
    prepared.inventory_cost.issue_cost_byn = "13.00";
    prepared.posting.lines.forEach(line => { line.amount = "13.00"; });
  }
  if (mismatch === "basis") prepared.inventory_cost.basis_digest = "c".repeat(64);
  if (mismatch === "debit") prepared.posting.lines[0].account = "25";
  if (mismatch === "empty-debit") prepared.posting.lines[0].account = "";
  if (mismatch === "zero") { prepared.zero_value = true; prepared.inventory_cost.issue_cost_byn = "0.00"; }
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => Response.json(
    String(url).endsWith("production-material-issue-posting-preview") ? prepared : result)));
  render(<AccountingProductionMaterialCost org="1" month="2026-10" policyId="2" disabled={false} />);
  fill(); fireEvent.click(screen.getByText("Проверить материал и НЗП"));
  await screen.findByText(/Проводка не создана/);
  fireEvent.click(screen.getByText("Подготовить подтверждение проводки"));
  await screen.findByRole("alert");
  expect(screen.queryByText(/Пакет проводки подготовлен/)).not.toBeInTheDocument();
  expect(screen.queryByText("Провести проверенный материал")).not.toBeInTheDocument();
});

it("keeps explicit manual material accounts as an opt-in", async () => {
  const request = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    void url; void init;
    return Response.json(result);
  });
  vi.stubGlobal("fetch", request);
  render(<AccountingProductionMaterialCost org="1" month="2026-10" policyId="2" disabled={false} />);
  expect(screen.queryByLabelText("Счёт материала")).not.toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("Выбрать счёт материалов вручную"));
  expect(screen.getByLabelText("Счёт материала")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("Счёт материала"), { target: { value: "10.1" } });
  fill(); fireEvent.click(screen.getByText("Проверить материал и НЗП"));
  await screen.findByText(/Дт 20 12.50 BYN/);
  expect(JSON.parse(String(request.mock.calls[0][1]?.body)).account).toBe("10.1");
});
