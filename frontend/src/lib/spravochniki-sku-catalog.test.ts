import { describe, expect, it } from "vitest";

import type { NomenclatureGroup, SkuRow } from "./reference-data";
import { categoryNameMap, filterSkusByCategory, filterSkusBySearch } from "./spravochniki-sku-catalog";

function sku(over: Partial<SkuRow> = {}): SkuRow {
  return {
    code: "КА-00001",
    title: "Реле 12В",
    unit: "шт",
    category_id: null,
    vat_code: null,
    ...over,
  };
}

describe("filterSkusBySearch", () => {
  it("returns all rows for empty query", () => {
    const rows = [sku(), sku({ code: "КА-00002" })];
    expect(filterSkusBySearch(rows, "")).toHaveLength(2);
    expect(filterSkusBySearch(rows, "   ")).toHaveLength(2);
  });

  it("matches by title case-insensitively", () => {
    const rows = [sku({ title: "Аккумулятор литиевый SAMSUNG 3INR18650-25R" }), sku({ title: "Реле 12В" })];
    expect(filterSkusBySearch(rows, "samsung")).toHaveLength(1);
  });

  it("matches by code", () => {
    const rows = [sku({ code: "КА-00004438" }), sku({ code: "AKB-100" })];
    expect(filterSkusBySearch(rows, "ка-00004438")).toHaveLength(1);
  });

  it("returns empty when nothing matches", () => {
    const rows = [sku()];
    expect(filterSkusBySearch(rows, "нет такого")).toHaveLength(0);
  });
});

describe("filterSkusByCategory", () => {
  it("returns all rows when categoryId is null", () => {
    const rows = [sku({ category_id: 1 }), sku({ category_id: null })];
    expect(filterSkusByCategory(rows, null)).toHaveLength(2);
  });

  it("filters to exact category_id", () => {
    const rows = [sku({ category_id: 1 }), sku({ category_id: 2 }), sku({ category_id: null })];
    expect(filterSkusByCategory(rows, 1)).toHaveLength(1);
  });
});

describe("categoryNameMap", () => {
  it("maps id to name", () => {
    const groups: NomenclatureGroup[] = [
      { id: 1, code: "01", name: "Батарейки", parent_id: null, is_active: true },
      { id: 2, code: "02", name: "Реле", parent_id: null, is_active: true },
    ];
    const map = categoryNameMap(groups);
    expect(map.get(1)).toBe("Батарейки");
    expect(map.get(2)).toBe("Реле");
    expect(map.get(3)).toBeUndefined();
  });
});
