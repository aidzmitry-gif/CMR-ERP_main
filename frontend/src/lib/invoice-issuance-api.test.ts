import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { allocationError, exact, invoiceItems, issueInvoice, loadPending, prepareCommand, savePending, validatePreview } from "./invoice-issuance-api";

import { input, preview, result, response, command } from "@/test/invoice-issuance-fixtures";

beforeEach(() => sessionStorage.clear());
afterEach(() => vi.unstubAllGlobals());
describe("ERP invoice exact contract", () => {
  it.each(["", "-1", "1e3", "NaN", "1.234"])("rejects invalid decimal %s", value => expect(() => exact(value)).toThrow());
  it("normalizes strings without float arithmetic", () => expect(exact("000123,4")).toBe("123.40"));
  it("accepts known zero and nullable unknown warehouse basis", () => {
    const p = preview(); p.availability.rows.push({ sku_code: "SKU", warehouse: "UNKNOWN", physical: null, reserved: "1.00", free: null }); p.availability.basis_by_warehouse.UNKNOWN = { version: null, cutoff: null };
    expect(validatePreview(p, "1", input)).toBe(p);
    expect(allocationError(p, [{ line_no: 1, warehouse: "UNKNOWN", qty: "2" }])).toMatch(/известной/);
    p.availability.rows[0].free = "0.00";
    expect(allocationError(p, [{ line_no: 1, warehouse: "W", qty: "2" }])).toMatch(/превышает/);
  });
  it.each(["-1.00", "0.00", "1.99"])("does not overallocate free=%s", free => {
    const p = preview(); p.availability.rows[0].free = free;
    expect(allocationError(p, [{ line_no: 1, warehouse: "W", qty: "2" }])).not.toBeNull();
  });
  it("aggregates the same SKU across distinct invoice lines", () => {
    const p = preview(); p.lines.push({ ...p.lines[0], line_no: 2, item_id: 12 });
    expect(allocationError(p, [{ line_no: 1, warehouse: "W", qty: "2" }, { line_no: 2, warehouse: "W", qty: "2" }])).toMatch(/превышает/);
  });
  it("rejects duplicate line/warehouse and incomplete allocations", () => {
    expect(allocationError(preview(), [{ line_no: 1, warehouse: "W", qty: "1" }, { line_no: 1, warehouse: "W", qty: "1" }])).toMatch(/Объедините/);
    expect(allocationError(preview(), [{ line_no: 1, warehouse: "W", qty: "1" }])).toMatch(/полностью/);
  });
  it.each(["organization", "deal", "price", "currency", "availability"])("rejects mismatched %s", field => {
    const p = preview();
    if (field === "organization") p.organization_id = 8;
    if (field === "deal") p.deal_id = 2;
    if (field === "price") p.lines[0].price = "101.00";
    if (field === "currency") p.currency = "USD";
    if (field === "availability") p.availability.organization_id = 8;
    expect(() => validatePreview(p, "1", input)).toThrow();
  });
  it("keeps HTTP 403 visible instead of empty goods", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({}, 403)));
    await expect(invoiceItems("1")).rejects.toMatchObject({ status: 403 });
  });
  it("adapts real DealItemOut names", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response([{ id: 11, code: "SKU", title: "Товар", qty: 2 }])));
    expect(await invoiceItems("1")).toEqual([{ id: 11, sku_code: "SKU", name: "Товар", qty: 2 }]);
  });
  it("replays the identical endpoint and full body after a lost response", async () => {
    const pending = command(); savePending(pending);
    const fetch = vi.fn().mockRejectedValueOnce(new TypeError("network")); vi.stubGlobal("fetch", fetch);
    await expect(issueInvoice(pending)).rejects.toMatchObject({ uncertain: true });
    const restored = loadPending("1")!;
    fetch.mockResolvedValueOnce(response({ ...result, replayed: true })).mockResolvedValueOnce(response([result.document]));
    expect((await issueInvoice(restored)).replayed).toBe(true);
    expect(fetch.mock.calls[0]).toEqual(fetch.mock.calls[1]);
    expect(loadPending("2")).toBeNull();
  });
  it("keeps an unverified success uncertain if scoped document list disagrees", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response(result)).mockResolvedValueOnce(response([])));
    await expect(issueInvoice(command())).rejects.toMatchObject({ uncertain: true });
  });
  it("retains the first-draft endpoint on reload", () => {
    const p = preview(); p.document_id = 22;
    const pending = prepareCommand("1", 22, input, p, [{ line_no: 1, warehouse: "W", qty: "2" }], "Журнал");
    savePending(pending);
    expect(loadPending("1")?.endpoint).toBe("/api/sales/documents/22/issue");
    expect(JSON.parse(pending.body)).not.toHaveProperty("kind");
  });
});


it.each(["reserved", "fake_digest", "wrong_mode"])("rejects contradictory on-order response: %s", async variant => {
  const values = { ...input, reserve_mode: "on_order" as const };
  const p = { ...preview(), reserve_mode: "on_order" as const, availability: null };
  expect(validatePreview(p, "1", values)).toBe(p);
  const pending = prepareCommand("1", undefined, values, p, [], "");
  const issued = { ...result, reservation_digest: null as string | null, document: { ...result.document, reserve_mode: "on_order", reserve_status: "unreserved" } };
  if (variant === "reserved") issued.document.reserve_status = "reserved";
  if (variant === "fake_digest") issued.reservation_digest = "f".repeat(64);
  if (variant === "wrong_mode") issued.document.reserve_mode = "stock";
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(issued)));
  await expect(issueInvoice(pending)).rejects.toMatchObject({ uncertain: true });
});
