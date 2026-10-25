import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ScopedWmsReconciliation, WmsReconciliation } from "@/components/erp/wms-reconciliation";
import type { Reconciliation } from "@/lib/wms-warehouse";

const mocks = vi.hoisted(() => ({ organizationId: 3, allowed: true, fetch: vi.fn() }));
vi.mock("@/lib/wms-warehouse", () => ({ fetchRecon: mocks.fetch }));
vi.mock("@/components/instance-organization-gate", () => ({
  InstanceOrganizationGate: ({ children }: { children: (organization: { id: number }) => React.ReactNode }) =>
    mocks.allowed ? children({ id: mocks.organizationId }) : <p>Компания недоступна</p>,
}));
const data = (id = 3): Reconciliation => ({
  organization_id: id, gateway: false, total_abs_diff_value: null,
  source_unavailable_reason: "organization_stock_source_unverified",
  rows: [{ sku_code: "SYNTH", title: `Own ${id}`, warehouse: "Shared", wms_qty: 7, onec_qty: null, diff: null, diff_value: null }],
});
beforeEach(() => { mocks.organizationId = 3; mocks.allowed = true; mocks.fetch.mockReset(); });
afterEach(cleanup);

it("shows own quantity and unknown comparison without a zero valuation", () => {
  render(<WmsReconciliation initial={data()} />);
  expect(screen.getByText("Own 3")).toBeInTheDocument();
  expect(screen.getByText("7")).toBeInTheDocument();
  expect(screen.getByText("Неизвестно")).toBeInTheDocument();
  expect(screen.getAllByText("—")).toHaveLength(3);
  expect(screen.queryByText(/сходится|0 Br|0,00/)).not.toBeInTheDocument();
});
it("empty own journal never claims agreement with 1C", () => {
  render(<WmsReconciliation initial={{ ...data(), rows: [] }} />);
  expect(screen.getByText(/Сверка с 1С не подтверждена/)).toBeInTheDocument();
  expect(screen.getByText("Неизвестно")).toBeInTheDocument();
});
it("read error is explicit and offers retry", () => {
  const retry = vi.fn(); render(<WmsReconciliation initial={null} onRetry={retry} />);
  expect(screen.getByRole("alert")).toHaveTextContent("неизвестны");
  fireEvent.click(screen.getByRole("button", { name: "Повторить загрузку" }));
  expect(retry).toHaveBeenCalledOnce();
});
it("loads the instance company without a per-page selector", async () => {
  mocks.fetch.mockResolvedValue(data()); render(<ScopedWmsReconciliation />);
  expect(screen.getByRole("status")).toHaveTextContent("Загрузка");
  await screen.findByText("Own 3");
  expect(mocks.fetch).toHaveBeenCalledWith(3, expect.any(AbortSignal));
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
});
it("retry replaces an error with a fresh scoped read", async () => {
  mocks.fetch.mockResolvedValueOnce(null).mockResolvedValueOnce(data()); render(<ScopedWmsReconciliation />);
  await screen.findByRole("alert"); fireEvent.click(screen.getByRole("button", { name: "Повторить загрузку" }));
  await screen.findByText("Own 3"); expect(mocks.fetch).toHaveBeenCalledTimes(2);
});
it("late response from a previous company cannot replace current data", async () => {
  let resolveOld!: (value: Reconciliation) => void;
  mocks.fetch.mockReturnValueOnce(new Promise<Reconciliation>(resolve => { resolveOld = resolve; })).mockResolvedValueOnce(data(4));
  const view = render(<ScopedWmsReconciliation />);
  await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(1));
  const oldSignal = mocks.fetch.mock.calls[0][1] as AbortSignal;
  mocks.organizationId = 4; view.rerender(<ScopedWmsReconciliation />);
  await screen.findByText("Own 4"); expect(oldSignal.aborted).toBe(true);
  resolveOld(data(3)); await waitFor(() => expect(screen.queryByText("Own 3")).not.toBeInTheDocument());
  expect(screen.getByText("Own 4")).toBeInTheDocument();
});
it("does not read when the instance company gate refuses access", () => {
  mocks.allowed = false; render(<ScopedWmsReconciliation />);
  expect(screen.getByText("Компания недоступна")).toBeInTheDocument(); expect(mocks.fetch).not.toHaveBeenCalled();
});
