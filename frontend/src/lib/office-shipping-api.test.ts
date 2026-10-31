import { webcrypto } from "node:crypto";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { hash } from "@/lib/expense-control-api";
import * as api from "@/lib/office-shipping-api";
import { intent, invoice, shippingFixture } from "@/test/office-shipping-fixtures";

beforeEach(() => { vi.stubGlobal("crypto", webcrypto); sessionStorage.clear(); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const json = (v: unknown, status = 200) => Response.json(v, { status });
describe("Office shipping native boundary", () => {
  it("reads an actual nullable ETA and keeps paid Office stage separate from planned shipment", async () => {
    const context = await shippingFixture({ resolved: true, stage: "paid" });
    expect((await api.parseShippingContext(context, 15)).logistics.shipment?.eta).toBeNull();
    expect(context.logistics.shipment?.status).toBe("planned");
  });
  it("rejects another document before disclosing a saved request", async () => {
    await expect(api.parseShippingContext(await shippingFixture({ prepared: true }), 16)).rejects.toThrow(/сверку/);
  });
  it("rejects a payload changed after its persisted hash", async () => {
    const context = await shippingFixture({ prepared: true }); context.request!.payload.intent.contact = "Чужой контакт";
    await expect(api.parseShippingContext(context, 15)).rejects.toThrow(/сверку/);
  });
  it("retains immutable history when the current document has changed", async () => {
    const context = await shippingFixture({ prepared: true });
    context.source_snapshot = { ...context.source_snapshot, address: "Новый учебный адрес" };
    context.source_sha256 = await hash(context.source_snapshot); context.source_matches_request = false;
    context.logistics = { state: "source_changed", intake_id: null, pending_reason: "", target: null, shipment: null };
    expect((await api.parseShippingContext(context, 15)).request?.source_snapshot.address).toBe("Учебная улица, 1");
  });
  it("rejects an association naming a different invoice hash", async () => {
    const context = await shippingFixture({ associated: true });
    context.association = { ...context.association!, exact_invoice: { ...invoice, expected_content_sha256: "d".repeat(64) } };
    await expect(api.parseShippingContext(context, 15)).rejects.toThrow(/сверку/);
  });
  it("rejects write capabilities without a current reviewer", async () => {
    const context = await shippingFixture(); context.is_current_reviewer = false;
    await expect(api.parseShippingContext(context, 15)).rejects.toThrow(/сверку/);
  });
  it("selects a precise Sales invoice through an explicitly scoped Accounting buyer", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(json({ organization_id: 7, counterparty_id: 8, items: [
      { source: "procurement", id: 9, number: "УЧ-ТН", version: 1, reference: "procurement:receipt:9:1" },
      { source: "sales", id: 22, number: "УЧ-СЧЁТ", version: 3, reference: "sales:document:22", content_sha256: invoice.expected_content_sha256 },
    ] })); vi.stubGlobal("fetch", fetcher);
    expect(await api.searchShippingInvoices(7, 8, "УЧ")).toEqual([{ number: "УЧ-СЧЁТ", exact_invoice: invoice }]);
    expect(String(fetcher.mock.calls[0]?.[0])).toContain("/organizations/7/settlement-documents?counterparty_id=8&q=");
  });
  it("does not synthesize an invoice hash when an older server omits it", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ organization_id: 7, counterparty_id: 8, items: [{ source: "sales", id: 22, number: "УЧ-СЧЁТ", version: 3, reference: "sales:document:22" }] })));
    await expect(api.searchShippingInvoices(7, 8, "УЧ")).rejects.toThrow(/точная версия/);
  });
  it("rejects a buyer register returned for another organization", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ organization_id: 99, counterparty_id: 8, items: [] })));
    await expect(api.searchShippingInvoices(7, 8, "УЧ")).rejects.toThrow(/другого юрлица/);
  });
  it("keeps the exact command across reload and does not expose another principal's journal", async () => {
    const context = await shippingFixture();
    const pending: api.PendingCommand = { version: 1, kind: "prepare", document_id: 15, principal: context.principal, body: { request_key: "same-key", expected_source_hash: context.source_sha256, expected_assignment_revision: 1, intent } };
    api.savePending(pending);
    expect(api.readPending(context.principal, 15)).toEqual(pending);
    expect(api.readPending("another-reviewer", 15)).toBeNull();
    expect(() => api.savePending({ ...pending, body: { ...pending.body, request_key: "different-key" } })).toThrow(/не выполнена/);
    const recovered = await shippingFixture({ prepared: true }); recovered.request!.request_key = "same-key";
    expect(api.pendingMatches(pending, recovered)).toBe(true); api.clearPending(pending);
    expect(api.readPending(context.principal, 15)).toBeNull();
  });
  it("marks a disconnected POST uncertain and never automatically repeats it", async () => {
    const context = await shippingFixture(); const fetcher = vi.fn(async () => { throw new TypeError("offline"); }); vi.stubGlobal("fetch", fetcher);
    const body = { request_key: "same-key", expected_source_hash: context.source_sha256, expected_assignment_revision: 1, intent };
    await expect(api.prepareShipping(15, body)).rejects.toMatchObject({ uncertain: true });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("distinguishes a definite permission denial from an uncertain command", async () => {
    const context = await shippingFixture(); vi.stubGlobal("fetch", vi.fn(async () => json({}, 403)));
    await expect(api.prepareShipping(15, { request_key: "denied", expected_source_hash: context.source_sha256, expected_assignment_revision: 1, intent })).rejects.toMatchObject({ uncertain: false, status: 403 });
  });
  it("uses a distinct confirmation key and matches all preserved invoice and intent evidence", async () => {
    const context = await shippingFixture({ prepared: true }); const body = await api.associationCommand(context, invoice, "Учебная сверка оригиналов");
    expect(body.request_key).not.toBe(context.request!.request_key);
    expect(body.expected_payload_hash).toBe(context.request!.payload_sha256);
    expect(body.evidence_refs.invoice_sha256).toBe(invoice.expected_content_sha256);
    vi.stubGlobal("fetch", vi.fn(async () => json({ ...context.request, exact_invoice: { ...invoice, expected_version: 4 }, intent_digest: body.expected_intent_digest, assignment_revision: 1, verified_invoice: { deal_id: 9 } })));
    await expect(api.previewAssociation(15, body)).rejects.toThrow(/сверку/);
  });
  it("normalizes decimal input without inventing a zero or rounding unconfirmed precision", () => {
    expect(api.decimalInput("700,5")).toBe("700.50"); expect(api.decimalInput("")).toBeNull();
    expect(api.decimalInput("1.999")).toBeNull(); expect(api.validIntent({ ...intent, pickup_date: "2026-02-30" })).toBe(false);
  });
});
