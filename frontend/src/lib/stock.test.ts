import { describe, expect, it } from "vitest";
import { aggregateStock, marginOf, srokOf, type SkuStock } from "@/lib/stock";
import type { StockRow } from "@/lib/api";

const row = (o: Partial<StockRow>): StockRow => ({
  sku_code: "A",
  warehouse: "Минск",
  qty_available: 0,
  qty_reserved: 0,
  qty_forecast: 0,
  price: 0,
  cost: null,
  ...o,
});

describe("aggregateStock", () => {
  it("свободный остаток = available − reserved, не ниже нуля", () => {
    const m = aggregateStock([row({ qty_available: 5, qty_reserved: 8 })]);
    expect(m.A.free).toBe(0); // 5 − 8 = −3 → clamp 0
  });

  it("суммирует free/forecast по нескольким складам одного SKU", () => {
    const m = aggregateStock([
      row({ warehouse: "Минск", qty_available: 10, qty_reserved: 2, qty_forecast: 4 }),
      row({ warehouse: "Гомель", qty_available: 3, qty_reserved: 0, qty_forecast: 1 }),
    ]);
    expect(m.A.free).toBe(11); // 8 + 3
    expect(m.A.forecast).toBe(5); // 4 + 1
    expect(m.A.warehouses).toHaveLength(2);
  });

  it("цена и себес берутся первыми ненулевыми (едины по складам)", () => {
    const m = aggregateStock([
      row({ price: 0, cost: null, qty_available: 1 }),
      row({ warehouse: "Гомель", price: 100, cost: 70, qty_available: 1 }),
    ]);
    expect(m.A.price).toBe(100);
    expect(m.A.cost).toBe(70);
  });

  it("склад без остатка и без прихода не попадает в разбивку", () => {
    const m = aggregateStock([row({ qty_available: 0, qty_reserved: 0, qty_forecast: 0 })]);
    expect(m.A.warehouses).toHaveLength(0);
  });
});

describe("srokOf", () => {
  const s = (o: Partial<SkuStock>): SkuStock => ({ price: 0, cost: null, free: 0, forecast: 0, warehouses: [], ...o });
  it("свободное → в наличии", () => expect(srokOf(s({ free: 3 })).label).toBe("в наличии"));
  it("только в пути → в пути", () => expect(srokOf(s({ forecast: 5 })).label).toBe("в пути"));
  it("ни того ни другого → под заказ", () => expect(srokOf(s({})).label).toBe("под заказ"));
  it("нет данных → под заказ", () => expect(srokOf(undefined).label).toBe("под заказ"));
});

describe("marginOf", () => {
  const s = (o: Partial<SkuStock>): SkuStock => ({ price: 0, cost: null, free: 0, forecast: 0, warehouses: [], ...o });
  it("маржа = (цена − себес)/цена", () => {
    const m = marginOf(s({ price: 100, cost: 70 }));
    expect(m?.gp).toBe(30);
    expect(Math.round(m!.pct)).toBe(30);
  });
  it("нет себес → null (честно, а не 0%)", () => expect(marginOf(s({ price: 100, cost: null }))).toBeNull());
  it("нет цены → null", () => expect(marginOf(s({ price: 0, cost: 10 }))).toBeNull());
});
