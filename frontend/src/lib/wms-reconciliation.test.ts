import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchRecon, fetchReconServer } from "@/lib/wms-warehouse";

afterEach(() => vi.restoreAllMocks());
const data = () => ({
  organization_id: 3, gateway: false, total_abs_diff_value: null,
  source_unavailable_reason: "organization_stock_source_unverified",
  rows: [{ sku_code: "SYNTH", title: "Own stock", warehouse: "Shared", wms_qty: 7, onec_qty: null, diff: null, diff_value: null }],
});
function respond(value: unknown, ok = true) {
  const fetch = vi.fn().mockResolvedValue({ ok, json: async () => value });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

describe("company reconciliation source boundary", () => {
  it("server read sends explicit company and existing authentication", async () => {
    const value = data(); const fetch = respond(value);
    expect(await fetchReconServer(3, "warehouse", { Authorization: "Bearer synthetic" })).toEqual(value);
    expect(fetch).toHaveBeenCalledWith("http://127.0.0.1:8000/wms/reconciliation?organization_id=3",
      expect.objectContaining({ headers: { Authorization: "Bearer synthetic" }, cache: "no-store" }));
  });
  it("rejects another company's otherwise valid response", async () => {
    respond({ ...data(), organization_id: 4 });
    expect(await fetchRecon(3)).toBeNull();
  });
  it.each([
    { rows: [{ sku_code: "A", title: "t", warehouse: "w", wms_qty: 1, onec_qty: 2, diff: -1, diff_value: -50 }], gateway: true, total_abs_diff_value: 50 },
    { ...data(), total_abs_diff_value: 0 },
    { ...data(), rows: [{ ...data().rows[0], wms_qty: Number.NaN }] },
    { ...data(), source_unavailable_reason: "unknown" },
    { ...data(), source_unavailable_reason: ["organization_stock_source_unverified"] },
  ])("rejects unscoped, fabricated zero, corrupt or unsupported responses %#", async value => {
    respond(value); expect(await fetchRecon(3)).toBeNull();
  });
  it("authorization failure is unavailable and preserves explicit client scope", async () => {
    const fetch = respond({}, false);
    expect(await fetchRecon(3)).toBeNull();
    expect(fetch).toHaveBeenCalledWith("/api/wms/reconciliation?organization_id=3", expect.objectContaining({ cache: "no-store" }));
  });
  it("does not fetch without a valid company", async () => {
    const fetch = respond(data());
    expect(await fetchRecon(0)).toBeNull(); expect(fetch).not.toHaveBeenCalled();
  });
  it("retains own journal when the gateway is disconnected", async () => {
    const value = { ...data(), source_unavailable_reason: "stock_gateway_unavailable" };
    respond(value); expect(await fetchRecon(3)).toEqual(value);
  });
});
