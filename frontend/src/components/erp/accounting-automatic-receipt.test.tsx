import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useState } from "react";
import { AccountingReceiptPreview } from "./accounting-receipt-preview";
import { ProcurementReceiptPosting } from "./procurement-receipt-posting";
import { AccountingAutomaticReceipt } from "./accounting-automatic-receipt";
import { ProcurementReceiptDrafts } from "./procurement-receipt-drafts";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear(); });
const options = { expected_version: 2, posting_date: "2026-09-02", policy_id: 3,
  settlement_account: "60.01", vat_account: null, inventory_accounts: ["41.01"] };
const result = { organization_id: 7, source: "procurement:receipt:9", source_version: 2,
  digest: "a".repeat(64), posted: false, resolved_options: options,
  lines: [{ account: "41.01", title: "Товары", side: "debit", amount: "100.01" }] };
const source = { id: 9, version: 2, document: { operation_date: "2026-09-02", items: [{ sku: "Товар", vat_amount: "0.00" }] } };

it.each(["accounting", "procurement"])("%s uses server-resolved accounts, immutable retry and stored readback", async surface => {
  const verified = vi.fn();
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => result })
    .mockRejectedValueOnce(new Error("Lost response"))
    .mockResolvedValueOnce({ ok: true, json: async () => ({ ...result, entry_id: 12 }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ organization_id: 7, id: 9, version: 2, status: "posted", entry_id: 12 }) });
  vi.stubGlobal("fetch", fetcher);
  if (surface === "accounting") render(<AccountingReceiptPreview org="7" source={source} onVerified={verified} />);
  else render(<ProcurementReceiptPosting org="7" receiptId={9} version={2} items={[{ sku: "Товар", lot: "lot" }]} accounts={[]} date="2026-09-02" onPosted={verified} onBusy={() => {}} />);
  expect(screen.queryByLabelText("Счёт расчётов с поставщиком")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Рассчитать автоматические проводки" }));
  expect(await screen.findByText(/Дт 41.01/)).toBeInTheDocument();
  expect(fetcher.mock.calls[0][0]).toMatch(/\/auto-preview$/);
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ expected_version: 2, posting_date: "2026-09-02" });
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить и провести поступление" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Параметры зафиксированы");
  expect(screen.getByLabelText("Выбрать счета вручную")).toBeDisabled();
  expect(verified).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Повторить подтверждение" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Операция № 12");
  expect(fetcher.mock.calls[1][0]).toMatch(/\/auto-confirm$/);
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ ...options, digest: result.digest });
  expect(fetcher.mock.calls[1][1].body).toBe(fetcher.mock.calls[2][1].body);
  expect(fetcher.mock.calls[3][0]).toMatch(/\/source$/);
  expect(verified).toHaveBeenCalledWith(12);
});

it.each([{ ...result, organization_id: 8 }, { ...result, resolved_options: { ...options, expected_version: 3 } }])("rejects mismatched automatic preview", async data => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => data }));
  render(<AccountingReceiptPreview org="7" source={source} />);
  fireEvent.click(screen.getByRole("button", { name: "Рассчитать автоматические проводки" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("не соответствует");
  expect(screen.queryByRole("button", { name: "Подтвердить и провести поступление" })).not.toBeInTheDocument();
});

it("blocks a first confirm when the parent becomes busy after preview", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => result });
  vi.stubGlobal("fetch", fetcher);
  const props = { org: "7", receiptId: 9, version: 2, date: "2026-09-02", onLock: () => {} };
  const view = render(<AccountingAutomaticReceipt {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Рассчитать автоматические проводки" }));
  await screen.findByText(/Дт 41.01/);
  view.rerender(<AccountingAutomaticReceipt {...props} blocked />);
  expect(screen.getByRole("button", { name: "Подтвердить и провести поступление" })).toBeDisabled();
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("invalidates an unconfirmed procurement preview when its date changes", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => result }));
  const props = { org: "7", receiptId: 9, version: 2, items: [{ sku: "Товар", lot: "lot" }],
    accounts: [], onPosted: () => {}, onBusy: () => {} };
  const view = render(<ProcurementReceiptPosting {...props} date="2026-09-02" />);
  fireEvent.click(screen.getByRole("button", { name: "Рассчитать автоматические проводки" }));
  await screen.findByText(/Дт 41.01/);
  view.rerender(<ProcurementReceiptPosting {...props} date="2026-09-03" />);
  expect(screen.queryByRole("button", { name: "Подтвердить и провести поступление" })).not.toBeInTheDocument();
  expect(screen.getByText("Дата отражения: 2026-09-03.")).toBeInTheDocument();
});

it("releases the caller busy state when a date change aborts an in-flight preview", async () => {
  let signal: AbortSignal | undefined;
  vi.stubGlobal("fetch", vi.fn((_url: string, init: RequestInit) => {
    signal = init.signal as AbortSignal;
    return new Promise(() => {});
  }));
  function Caller({ date }: { date: string }) {
    const [busy, setBusy] = useState(false);
    return <ProcurementReceiptPosting org="7" receiptId={9} version={2} items={[]}
      accounts={[]} date={date} blocked={busy} onBusy={setBusy} onPosted={() => {}} />;
  }
  const view = render(<Caller date="2026-09-02" />);
  fireEvent.click(screen.getByRole("button", { name: "Рассчитать автоматические проводки" }));
  expect(screen.getByRole("button", { name: "Рассчитать автоматические проводки" })).toBeDisabled();
  view.rerender(<Caller date="2026-09-03" />);
  expect(signal?.aborted).toBe(true);
  expect(screen.getByRole("button", { name: "Рассчитать автоматические проводки" })).toBeEnabled();
});

it("invalidates manual fallback preview when date or policy changes", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => result }));
  const props = { org: "7", receiptId: 9, version: 2, items: [{ sku: "Товар", lot: "lot" }],
    accounts: [
      { code: "41.01", title: "Товары", category: "asset", cash: false, quantity_tracking: true },
      { code: "60.01", title: "Поставщики", category: "liability", cash: false, quantity_tracking: false },
    ], onPosted: () => {}, onBusy: () => {} };
  const view = render(<ProcurementReceiptPosting {...props} date="2026-09-02" policyId={3} />);
  fireEvent.click(screen.getByLabelText("Выбрать счета вручную"));
  fireEvent.change(screen.getByLabelText("Счёт расчётов с поставщиком"), { target: { value: "60.01" } });
  fireEvent.change(screen.getByLabelText("Счёт НДС накладной"), { target: { value: "none" } });
  fireEvent.change(screen.getByLabelText("Счёт позиции накладной 1"), { target: { value: "41.01" } });
  fireEvent.click(screen.getByRole("button", { name: "Рассчитать проводки накладной" }));
  await screen.findByRole("button", { name: "Провести сохранённую накладную" });
  view.rerender(<ProcurementReceiptPosting {...props} date="2026-09-03" policyId={4} />);
  expect(screen.queryByRole("button", { name: "Провести сохранённую накладную" })).not.toBeInTheDocument();
});

it("retains a lost confirmation through date and policy refresh in the real draft caller", async () => {
  const document = { currency: "BYN", invoice_reference: "AUTO-9", document_date: "2026-09-02",
    operation_date: "2026-09-02", supplier: "Поставщик", supplier_id: 19,
    supplier_unp: "190000001", contract: "Без договора", contract_basis: "Поставка без договора",
    warehouse: "receiving", warehouse_id: 9, warehouse_title: "Склад", explanation: "Товар",
    items: [{ order_id: null, sku_id: 31, sku_title: "Товар", sku: "Товар", unit: "шт", lot: "lot",
      quantity: "1.000000", net_amount: "100.01", vat_rate: "0", vat_amount: "0.00", vat_basis: "ОСН" }] };
  const row = { id: 9, version: 2, status: "draft", posting: null,
    revisions: [{ version: 2, actor: "buyer", created_at: "2026-09-02", document }] };
  let confirms = 0;
  const fetcher = vi.fn(async (url: string) => {
    if (url.endsWith("/auto-preview")) return { ok: true, json: async () => result };
    if (url.endsWith("/auto-confirm")) {
      if (++confirms === 1) throw new Error("Lost response");
      return { ok: true, json: async () => ({ ...result, entry_id: 12 }) };
    }
    if (url.endsWith("/source")) return { ok: true, json: async () => ({ organization_id: 7,
      id: 9, version: 2, status: "posted", entry_id: 12 }) };
    if (url.includes("supplier-contracts")) return { ok: true, json: async () => ({
      organization_id: 7, supplier_id: 19, status: "active", items: [], truncated: false }) };
    if (url.includes("purchase-ownership")) return { ok: true, json: async () => [] };
    if (url.includes("warehouses")) return { ok: true, json: async () => ({ organization_id: 7, items: [], truncated: false }) };
    return { ok: true, json: async () => confirms > 1
      ? [{ ...row, status: "posted", posting: { entry_id: 12, version: 2 } }] : [row] };
  });
  vi.stubGlobal("fetch", fetcher);
  const verified = vi.fn();
  const view = render(<ProcurementReceiptDrafts org="7" date="2026-09-02" policyId={3} onPosted={verified} />);
  fireEvent.click(await screen.findByRole("button", { name: /AUTO-9/ }));
  fireEvent.click(screen.getByRole("button", { name: "Рассчитать автоматические проводки" }));
  await screen.findByText(/Дт 41.01/);
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить и провести поступление" }));
  await screen.findByText(/Lost response/);
  expect(screen.getByLabelText("Номер первичной накладной")).toBeDisabled();
  view.rerender(<ProcurementReceiptDrafts org="7" date="2026-09-03" policyId={4} onPosted={verified} />);
  expect(screen.getByText("Дата отражения: 2026-09-02.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Повторить подтверждение" }));
  await screen.findByRole("link", { name: "Открыть проведённую накладную" });
  expect(verified).toHaveBeenCalledTimes(1);
  const calls = fetcher.mock.calls.filter(([url]) => url.endsWith("/auto-confirm"));
  expect(calls).toHaveLength(2);
  expect((calls[0] as unknown as [string, RequestInit])[1].body).toBe((calls[1] as unknown as [string, RequestInit])[1].body);
  expect(screen.getByRole("button", { name: "Новая первичная накладная" })).toBeEnabled();
});
