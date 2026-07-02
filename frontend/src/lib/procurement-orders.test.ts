import { describe, expect, it } from "vitest";

import { daysToEta, orderTotals, statusLabel, type OpenOrder } from "@/lib/procurement-orders";

describe("statusLabel", () => {
  it("переводит известные статусы", () => {
    expect(statusLabel("ordered")).toBe("Заказан");
    expect(statusLabel("shipped")).toBe("Отгружен");
    expect(statusLabel("customs")).toBe("Таможня");
  });
  it("неизвестный статус — как есть", () => {
    expect(statusLabel("received")).toBe("received");
  });
});

describe("daysToEta", () => {
  const now = Date.parse("2026-07-01T00:00:00Z");
  it("будущее — положительное", () => {
    expect(daysToEta("2026-07-15", now)).toBe(14);
  });
  it("прошлое — отрицательное (просрочено)", () => {
    expect(daysToEta("2026-06-25", now)).toBe(-6);
  });
  it("нет/битая дата — null", () => {
    expect(daysToEta(null, now)).toBeNull();
    expect(daysToEta("не-дата", now)).toBeNull();
  });
});

describe("orderTotals", () => {
  const orders: OpenOrder[] = [
    {
      id: 1,
      number: "PO-1",
      supplier: "S1",
      status: "shipped",
      eta_date: "2026-07-15",
      freight_byn: 200,
      lines: [
        { sku_code: "A", qty: 10, goods_value_byn: 100, weight: 5, volume: 0 },
        { sku_code: "B", qty: 5, goods_value_byn: 300, weight: 2, volume: 0 },
      ],
    },
    {
      id: 2,
      number: "PO-2",
      supplier: "S2",
      status: "customs",
      eta_date: null,
      freight_byn: 50,
      lines: [{ sku_code: "C", qty: 1, goods_value_byn: 600, weight: 1, volume: 0 }],
    },
  ];
  it("считает заказы/позиции/товар/фрахт", () => {
    expect(orderTotals(orders)).toEqual({ orders: 2, positions: 3, goods: 1000, freight: 250 });
  });
  it("пустой список — нули", () => {
    expect(orderTotals([])).toEqual({ orders: 0, positions: 0, goods: 0, freight: 0 });
  });
});
