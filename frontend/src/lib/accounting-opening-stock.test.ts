import { afterEach, describe, expect, it, vi } from "vitest";
import { openingRequest, pasteOpeningRows, readOpeningDraft } from "./accounting-opening-stock";

afterEach(() => vi.unstubAllGlobals());
describe("opening stock input", () => {
  it("preserves Excel decimal precision and separate stock layers", () => {
    expect(pasteOpeningRows("SKU\twarehouse\topening\t1 234,123456\t9 876,54"))
      .toEqual([{ sku: "SKU", warehouse: "warehouse", lot: "opening", quantity: "1234.123456", amount_byn: "9876.54" }]);
  });
  it("rejects missing columns and unknown or zero cost", () => {
    for (const text of ["SKU\tw\tl\t1", "SKU\tw\tl\t1\t0", "SKU\tw\tl\t1\tunknown", "SKU\tw\tl\t1\t1.001"])
      expect(() => pasteOpeningRows(text)).toThrow();
  });
  it("loads only a matching organization draft", () => {
    const document = { request_key: "00000000-0000-4000-8000-000000000001", opening_date: "2026-07-01", policy_id: 1,
      inventory_account: "41", counter_account: "80", evidence: "Synthetic report", rows: pasteOpeningRows("SKU\tw\tl\t1\t2") };
    const text = JSON.stringify({ format: "opening-stock-draft-v1", organization_id: 1, document });
    expect(readOpeningDraft(text, 1)).toEqual(document);
    expect(() => readOpeningDraft(text, 2)).toThrow();
  });
  it("restores an unfinished draft without inventing accounts or costs", () => {
    const document = { request_key: "00000000-0000-4000-8000-000000000001", opening_date: "2026-07-01", policy_id: 0,
      inventory_account: "", counter_account: "", evidence: "", rows: [{ sku: "", warehouse: "", lot: "", quantity: "", amount_byn: "" }] };
    expect(readOpeningDraft(JSON.stringify({ format: "opening-stock-draft-v1", organization_id: 1, document }), 1)).toEqual(document);
  });
  it("rejects foreign organization or malformed result", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ organization_id: 2, physical_stock_updated: false }) }));
    await expect(openingRequest(1, "preview", {})).rejects.toThrow("организации");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ organization_id: 1, physical_stock_updated: false, rows: [] }) }));
    await expect(openingRequest(1, "preview", {})).rejects.toThrow("повреждён");
  });
  it("distinguishes a rolled-back rejection from uncertain network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: "stale" }) }));
    await expect(openingRequest(1, "confirm", {})).rejects.toMatchObject({ rejected: true });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));
    await expect(openingRequest(1, "confirm", {})).rejects.toThrow("network");
  });
});
