import { describe, expect, it } from "vitest";

import {
  filterByQuery,
  filterByWarehouse,
  type StockMirrorRow,
  stockTotals,
} from "@/lib/wms-stock";

const rows: StockMirrorRow[] = [
  {
    sku_code: "AKB-60",
    title: "Аккумулятор 60 Ач",
    unit: "шт",
    warehouse: "Минск (центр.)",
    qty_available: 41,
    qty_reserved: 13,
    qty_free: 28,
    qty_forecast: 0,
    updated_at: null,
  },
  {
    sku_code: "AKB-60",
    title: "Аккумулятор 60 Ач",
    unit: "шт",
    warehouse: "Гомель",
    qty_available: 18,
    qty_reserved: 0,
    qty_free: 18,
    qty_forecast: 0,
    updated_at: null,
  },
  {
    sku_code: "ROLL-3",
    title: "Рулон стали 3 мм",
    unit: "т",
    warehouse: "Брест",
    qty_available: 25,
    qty_reserved: 0,
    qty_free: 25,
    qty_forecast: 0,
    updated_at: null,
  },
];

describe("filterByWarehouse", () => {
  it("без склада возвращает все строки", () => {
    expect(filterByWarehouse(rows, "")).toHaveLength(3);
  });
  it("фильтрует по конкретному складу", () => {
    expect(filterByWarehouse(rows, "Гомель")).toEqual([rows[1]]);
  });
});

describe("filterByQuery", () => {
  it("ищет по коду регистронезависимо", () => {
    expect(filterByQuery(rows, "akb")).toHaveLength(2);
  });
  it("ищет по названию", () => {
    expect(filterByQuery(rows, "рулон")).toEqual([rows[2]]);
  });
  it("пустой запрос — все строки", () => {
    expect(filterByQuery(rows, "  ")).toHaveLength(3);
  });
});

describe("stockTotals", () => {
  it("суммирует наличие/резерв/свободное и считает уникальные SKU", () => {
    expect(stockTotals(rows)).toEqual({
      available: 84,
      reserved: 13,
      free: 71,
      skuCount: 2, // AKB-60 на двух складах = 1 SKU
    });
  });
});
