import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { PurchaseChain } from "@/lib/procurement-machine";
import { ProcurementPurchaseChain } from "./procurement-purchase-chain";

const response = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300, status, json: async () => body,
}) as Response;
const chain = (org = 1, orderId = 7): PurchaseChain => ({
  organization_id: org,
  order: { id: orderId, number: `ORDER-${org}-${orderId}`, supplier: "Тестовый поставщик", status: "received", eta_date: null, freight_byn: "0.00", lines: [{ id: 11, sku_code: "TEST-331", quantity: "2.00", goods_value_byn: "100.00" }] },
  request_links: [{ id: 31, request_id: 41, ownership_id: 51, number: `REQUEST-${org}-${orderId}`, supplier: "Тестовый поставщик", item: "Тестовый товар", quantity: "2.00", planned_amount: "100.00", stage: "linked", evidence: "fixture-owned" }],
  receipts: [{ id: 21, source_key: "fixture331", version: 1, status: "posted", posting: { entry_id: 41, version: 1 }, invoice_reference: `INVOICE-${org}-${orderId}`, document_date: "2026-10-01", operation_date: "2026-10-01", supplier: "Тестовый поставщик", contract: null, warehouse: "Тестовый склад", lines: [{ order_line_id: 11, sku: "TEST-331", lot: null, quantity: "2.00", unit: "шт" }], physical_acceptance: [{ receipt_id: 61, source_version: 1, lines: [], evidence: "fixture-accepted", actor: "fixture", created_at: "2026-10-01T12:00:00Z" }] }],
  stages: { request: "linked", order: "owned", incoming_invoice: "posted", warehouse: "accepted" },
  status: "complete", blockers: [],
});
let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn(async () => response(chain()));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());
async function load() {
  fireEvent.click(screen.getByRole("button", { name: "Проверить цепочку" }));
  await screen.findByText("Цепочка подтверждена по сохранённым источникам.");
}
const noOldEvidence = () => {
  expect(screen.queryByText("Цепочка подтверждена по сохранённым источникам.")).not.toBeInTheDocument();
  expect(screen.queryByText(/REQUEST-1-7/)).not.toBeInTheDocument();
  expect(screen.queryByText(/INVOICE-1-7/)).not.toBeInTheDocument();
};

it("renders a complete scoped chain through the actual API adapter", async () => {
  render(<ProcurementPurchaseChain org={1} orderId={7} />);
  await load();
  expect(screen.getByText(/REQUEST-1-7/)).toBeInTheDocument();
  expect(screen.getByText(/INVOICE-1-7/)).toHaveTextContent("версия 1");
  expect(fetchMock).toHaveBeenCalledWith("/api/procurement/organizations/1/orders/7/chain", { cache: "no-store" });
});

it("keeps a genuinely incomplete empty chain distinct from confirmed sources", async () => {
  const partial: PurchaseChain = { ...chain(), request_links: [], receipts: [], stages: { request: "missing", order: "owned", incoming_invoice: "missing", warehouse: "missing" }, status: "partial", blockers: ["purchase_request_not_linked", "incoming_invoice_not_registered", "warehouse_receipt_not_accepted"] };
  fetchMock.mockResolvedValue(response(partial));
  render(<ProcurementPurchaseChain org={1} orderId={7} />);
  fireEvent.click(screen.getByRole("button", { name: "Проверить цепочку" }));
  await screen.findByText("Цепочка неполная. Реестр не считает отсутствующие документы выполненными.");
  expect(screen.getByText("заявка не связана с заказом")).toBeInTheDocument();
  expect(screen.getByText("складская приёмка не подтверждена")).toBeInTheDocument();
  noOldEvidence();
});

it.each([401, 403, 500])("removes old confirmation and documents when refresh returns %s", async status => {
  render(<ProcurementPurchaseChain org={1} orderId={7} />);
  await load();
  fetchMock.mockResolvedValue(response({ detail: "unavailable" }, status));
  fireEvent.click(screen.getByRole("button", { name: "Обновить цепочку" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(String(status));
  noOldEvidence();
  expect(fetchMock).toHaveBeenCalledTimes(2);
  fetchMock.mockResolvedValue(response(chain()));
  fireEvent.click(screen.getByRole("button", { name: "Проверить цепочку" }));
  await screen.findByText(/INVOICE-1-7/);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(3);
});

it("hides prior evidence while refresh is still pending", async () => {
  render(<ProcurementPurchaseChain org={1} orderId={7} />);
  await load();
  let finish!: (value: Response) => void;
  fetchMock.mockReturnValue(new Promise<Response>(resolve => { finish = resolve; }));
  fireEvent.click(screen.getByRole("button", { name: "Обновить цепочку" }));
  expect(screen.getByRole("button", { name: "Проверяем…" })).toBeDisabled();
  noOldEvidence();
  await act(async () => { finish(response(chain())); });
  expect(await screen.findByText(/INVOICE-1-7/)).toBeInTheDocument();
});

it.each([{ org: 1, orderId: 8 }, { org: 2, orderId: 7 }])(
  "isolates $org/$orderId from an old late chain response", async ({ org, orderId }) => {
    const view = render(<ProcurementPurchaseChain org={1} orderId={7} />);
    await load();
    let finishOld!: (value: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise<Response>(resolve => { finishOld = resolve; }));
    fireEvent.click(screen.getByRole("button", { name: "Обновить цепочку" }));
    view.rerender(<ProcurementPurchaseChain org={org} orderId={orderId} />);
    noOldEvidence();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    fetchMock.mockResolvedValue(response(chain(org, orderId)));
    fireEvent.click(screen.getByRole("button", { name: "Проверить цепочку" }));
    await screen.findByText(`INVOICE-${org}-${orderId} · версия 1 · проведена`);
    await act(async () => { finishOld(response(chain())); });
    await waitFor(() => expect(screen.getByRole("button", { name: "Обновить цепочку" })).toBeEnabled());
    expect(screen.queryByText(/REQUEST-1-7/)).not.toBeInTheDocument();
    expect(screen.queryByText(/INVOICE-1-7/)).not.toBeInTheDocument();
    expect(screen.getByText("Цепочка подтверждена по сохранённым источникам.")).toBeInTheDocument();
    expect(screen.getByText(`INVOICE-${org}-${orderId} · версия 1 · проведена`)).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/procurement/organizations/1/orders/7/chain",
      "/api/procurement/organizations/1/orders/7/chain",
      `/api/procurement/organizations/${org}/orders/${orderId}/chain`,
    ]);
  },
);
