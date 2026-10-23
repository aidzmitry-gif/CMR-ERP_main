import { describe, expect, it } from "vitest";
import { readPickerPrices } from "./catalog-picker-prices";

function priceFeed(price = "12.50", skuId = 1) {
  return { status: "reference", snapshot: { id: "00000000-0000-0000-0000-000000000101", kind: "Synthetic wholesale",
    source_as_of: "2026-10-23T12:00:00", observed_at: "2026-10-23T09:00:00Z", row_count: 1,
    response_complete: true, full_coverage: false, activity_verified: false, mapped: 1, held: 0, unmapped: 0 },
    rows: [{ sku_id: skuId, sku_code: "SYNTHETIC", unit: "unit", price, currency: "933",
      kind: "Synthetic wholesale", price_includes_vat: false, effective_at: "2026-10-22T00:00:00",
      characteristic_guid: "00000000-0000-0000-0000-000000000000",
      package_guid: "00000000-0000-0000-0000-000000000000", application_status: "reference_only" }] };
}

describe("reference-price boundary", () => {
  it("retains a full-precision amount as a string", () => {
    const raw = priceFeed("999999999999999999.1234567890");
    expect(readPickerPrices(raw)?.rows[0].price).toBe(raw.rows[0].price);
  });
  it("keeps explicit zero as reference", () => {
    expect(readPickerPrices(priceFeed("0.00"))?.rows[0]).toMatchObject({ price: "0.00", application_status: "reference_only" });
  });
  it("accepts unknown as empty unavailable, with no zero substitution", () => {
    expect(readPickerPrices({ status: "unavailable", snapshot: null, rows: [] })).toEqual({ status: "unavailable", snapshot: null, rows: [] });
  });
  it.each([
    () => null,
    () => ({ ...priceFeed(), rows: {} }),
    () => { const raw = priceFeed(); return { ...raw, rows: [{ ...raw.rows[0], price: undefined }] }; },
    () => { const raw = priceFeed(); return { ...raw, rows: [{ ...raw.rows[0], effective_at: undefined }] }; },
    () => { const raw = priceFeed(); return { ...raw, rows: [{ ...raw.rows[0], sku_id: "__proto__" }] }; },
    () => { const raw = priceFeed(); raw.snapshot.full_coverage = true; return raw; },
    () => ({ ...priceFeed(), status: "unavailable" }),
    () => { const raw = priceFeed(); raw.snapshot.mapped = 0; return raw; },
  ])("rejects damaged rows/envelopes instead of passing them to render %#", make => {
    expect(readPickerPrices(make())).toBeNull();
  });
  it("rejects repeated source dimensions instead of showing conflicting prices", () => {
    const raw = priceFeed(); raw.rows.push({ ...raw.rows[0], price: "99.00" });
    raw.snapshot.row_count = raw.snapshot.mapped = 2;
    expect(readPickerPrices(raw)).toBeNull();
  });
});
