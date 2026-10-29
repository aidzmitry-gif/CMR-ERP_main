import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchCostCatalog, fetchOwnedCostReview, formatFreightByn, parseCostCatalog, parseOwnedCostReview,
  type OwnedCostReview,
} from "@/lib/logistics-owned-costs";

const selected = { organization_id: 1, principal: "stable-cost-subject" };
function known(): OwnedCostReview {
  return { ...selected, version: 1, status: "partial", complete_cost_coverage: false,
    source: "explicit_own_logistics_imports", posting_status: "not_verified",
    unavailable_sections: ["tariffs", "tenders", "audit"], import_freight: {
      status: "known", qualified_import_count: 3, warehouse_import_count: 2, known_count: 2,
      unpriced_count: 0, excluded_nonwarehouse_count: 1, known_total: "17000.00", total: "17000.00", known_average: "8500.00",
    } };
}

afterEach(() => vi.unstubAllGlobals());

describe("qualified logistics cost decoder", () => {
  it("accepts exact qualified sums without claiming full or posted costs", () => {
    expect(parseOwnedCostReview(known(), selected).import_freight.total).toBe("17000.00");
  });
  it("keeps absent sources and unknown amounts distinct from zero", () => {
    const value = known();
    value.import_freight = { status: "unknown", qualified_import_count: 0, warehouse_import_count: 0,
      known_count: 0, unpriced_count: 0, excluded_nonwarehouse_count: 0, known_total: null, total: null, known_average: null };
    expect(parseOwnedCostReview(value, selected).import_freight.total).toBeNull();
  });
  it("accepts only the known subtotal when an amount is unpriced", () => {
    const value = known();
    Object.assign(value.import_freight, { status: "partial", qualified_import_count: 4, warehouse_import_count: 3,
      unpriced_count: 1, total: null });
    expect(parseOwnedCostReview(value, selected).import_freight.known_total).toBe("17000.00");
  });
  it.each(["organization_id", "principal"] as const)("refuses a different %s", key => {
    const value = known();
    Object.assign(value, { [key]: key === "principal" ? "other-subject" : 2 });
    expect(() => parseOwnedCostReview(value, selected)).toThrow();
  });
  it.each([
    "count", "status", "qualified", "total", "average", "money", "coverage", "unavailable",
  ])("refuses inconsistent %s", kind => {
    const value = known();
    switch (kind) {
      case "count": value.import_freight.known_count = 3; break;
      case "status": value.import_freight.status = "partial"; break;
      case "qualified": value.import_freight.qualified_import_count = 4; break;
      case "total": value.import_freight.total = "17000.01"; break;
      case "average": value.import_freight.known_average = "8500.01"; break;
      case "money": value.import_freight.known_total = "17e3"; break;
      case "coverage": Object.assign(value, { complete_cost_coverage: true }); break;
      case "unavailable": value.unavailable_sections = []; break;
    }
    expect(() => parseOwnedCostReview(value, selected)).toThrow();
  });
  it("validates the catalog identity and unique authorized organization IDs", () => {
    const catalog = { version: 1, principal: selected.principal, items: [{ id: 1, name: "Synthetic A", unp: "" }] };
    expect(parseCostCatalog(catalog)).toEqual(catalog);
    expect(() => parseCostCatalog({ ...catalog, principal: "" })).toThrow();
    expect(() => parseCostCatalog({ ...catalog, items: [...catalog.items, ...catalog.items] })).toThrow();
  });
  it("uses only no-store GETs for the catalog and explicit selected company", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ version: 1, principal: selected.principal, items: [] })))
      .mockResolvedValueOnce(new Response(JSON.stringify(known())));
    vi.stubGlobal("fetch", fetch);
    const signal = new AbortController().signal;
    await fetchCostCatalog(signal);
    await fetchOwnedCostReview(selected, signal);
    expect(fetch.mock.calls).toEqual([
      ["/api/logistics/cost-organizations", { cache: "no-store", signal }],
      ["/api/logistics/organizations/1/cost-insights", { cache: "no-store", signal }],
    ]);
  });
  it.each([401, 403, 409, 503])("preserves failure %i without decoding or displaying its body", async status => {
    const json = vi.fn().mockResolvedValue({ detail: "private raw detail" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status, json }));
    await expect(fetchOwnedCostReview(selected)).rejects.toMatchObject({ status });
    expect(json).not.toHaveBeenCalled();
  });
  it("refuses an invalid organization before a request", async () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    await expect(fetchOwnedCostReview({ ...selected, organization_id: 0 })).rejects.toThrow();
    expect(fetch).not.toHaveBeenCalled();
  });
  it("retains exact cents above Number precision in validation and display", () => {
    const value = known();
    value.import_freight = { ...value.import_freight, qualified_import_count: 1, warehouse_import_count: 1,
      known_count: 1, excluded_nonwarehouse_count: 0, known_total: "9007199254740993.01",
      total: "9007199254740993.01", known_average: "9007199254740993.01" };
    expect(parseOwnedCostReview(value, selected).import_freight.total).toBe("9007199254740993.01");
    expect(formatFreightByn(value.import_freight.total).replace(/\s/g, " ")).toBe("9 007 199 254 740 993,01 Br");
    expect(formatFreightByn(null)).toBe("Не определён");
  });
});
