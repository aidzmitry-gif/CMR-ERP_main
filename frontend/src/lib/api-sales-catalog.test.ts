import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchSalesSkusStrict, SalesCatalogError } from "./api";

const sku = { id: 17, code: "SYNTHETIC-BATTERY", title: "Учебная батарея", unit: "шт" };
const response = (value: unknown, status = 200) => ({ ok: status === 200, status, json: async () => value });
afterEach(() => vi.unstubAllGlobals());

describe("Sales catalogue boundary", () => {
  it("uses the Sales route and returns only the four permitted fields", async () => {
    const fetcher = vi.fn().mockResolvedValue(response([{ ...sku, internal_note: "synthetic private field" }]));
    vi.stubGlobal("fetch", fetcher);
    await expect(fetchSalesSkusStrict()).resolves.toEqual([sku]);
    expect(fetcher).toHaveBeenCalledWith("/api/sales/skus?for_picker=1", { cache: "no-store" });
  });
  it("accepts a confirmed empty list", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response([])));
    await expect(fetchSalesSkusStrict()).resolves.toEqual([]);
  });
  it.each([401, 403, 503])("preserves HTTP %s as failure", async (status) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response([], status)));
    await expect(fetchSalesSkusStrict()).rejects.toMatchObject({ status });
  });
  it("does not turn a transport failure into an empty list", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    await expect(fetchSalesSkusStrict()).rejects.toThrow("offline");
  });
  it.each([
    { result: [sku] },
    [{ ...sku, id: 0 }],
    [{ ...sku, title: "" }],
    [{ ...sku, unit: null }],
    [sku, { ...sku, code: "OTHER" }],
    [sku, { ...sku, id: 18 }],
  ])("rejects the whole malformed or ambiguous response %#", async (value) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(value)));
    await expect(fetchSalesSkusStrict()).rejects.toBeInstanceOf(SalesCatalogError);
  });
});
