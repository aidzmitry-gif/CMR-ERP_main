import { describe, expect, it } from "vitest";
import { aggregateCostSource, marginBySku, type CostSource, type MarginLine } from "@/lib/margin";

function line(over: Partial<MarginLine>): MarginLine {
  return {
    sku_code: "X", title: "t", qty: 1,
    unit_price: 100, revenue: 100, unit_landed_cost: 60, cogs: 60, margin_pct: 40,
    status: "priced", cost_shipment_id: null, cost_fixed_at: null, cost_fx_rate: null,
    cost_source: "onec", price_source: "quote",
    ...over,
  };
}

describe("aggregateCostSource", () => {
  it("нет priced-строк с источником → null", () => {
    expect(aggregateCostSource([])).toBeNull();
    expect(aggregateCostSource([line({ cost_source: null })])).toBeNull();
  });

  it("все priced одного источника → этот источник", () => {
    const src: CostSource = "demo";
    expect(aggregateCostSource([line({ cost_source: src }), line({ cost_source: src })])).toBe("demo");
  });

  it("разные источники у priced → mixed (нельзя приписывать один ярлык всей сделке)", () => {
    expect(
      aggregateCostSource([line({ cost_source: "onec" }), line({ cost_source: "landed" })]),
    ).toBe("mixed");
  });

  it("не-priced строки игнорируются при определении источника", () => {
    // landed-строка стоит, но она no_cost → не должна делать сделку «mixed».
    expect(
      aggregateCostSource([
        line({ cost_source: "onec", status: "priced" }),
        line({ cost_source: "landed", status: "no_cost" }),
      ]),
    ).toBe("onec");
  });
});

describe("marginBySku", () => {
  it("индексирует строки по коду; null → пустая карта", () => {
    expect(marginBySku(null).size).toBe(0);
    const m = marginBySku({
      deal_id: 1, revenue: 0, cogs_landed: null, gross_profit: null, margin_pct: null,
      priced_count: 0, total_count: 1, reason: null,
      lines: [line({ sku_code: "AKB-60" })],
    });
    expect(m.get("AKB-60")?.sku_code).toBe("AKB-60");
  });
});
