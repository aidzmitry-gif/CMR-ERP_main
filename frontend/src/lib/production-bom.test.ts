import { describe, expect, it } from "vitest";

import {
  available,
  type Bom,
  bomCounts,
  bomStatusLabel,
  type BomItem,
  coverageTone,
  itemStatusLabel,
  shortItemCount,
} from "@/lib/production-bom";

function bom(over: Partial<Bom> = {}): Bom {
  return {
    id: 1,
    product: "АКБ 48V 100Ah",
    version: "v1",
    status: "draft",
    note: "",
    item_count: 0,
    coverage: 100,
    ...over,
  };
}

function item(over: Partial<BomItem> = {}): BomItem {
  return {
    id: 1,
    bom_id: 1,
    component: "BMS 16S",
    norm_qty: 1,
    unit: "шт",
    stock: 10,
    reserved: 2,
    status: "ok",
    ...over,
  };
}

describe("production-bom", () => {
  it("bomStatusLabel: подписи статусов спецификации", () => {
    expect(bomStatusLabel("draft")).toBe("Черновик");
    expect(bomStatusLabel("approved")).toBe("Утверждена");
  });

  it("itemStatusLabel: подписи статусов позиции", () => {
    expect(itemStatusLabel("ok")).toBe("В наличии");
    expect(itemStatusLabel("short")).toBe("Дефицит");
  });

  it("available: склад минус резерв", () => {
    expect(available({ stock: 10, reserved: 2 })).toBe(8);
    expect(available({ stock: 5, reserved: 9 })).toBe(-4);
  });

  it("coverageTone: тон по порогам 100/80", () => {
    expect(coverageTone(100)).toContain("green");
    expect(coverageTone(120)).toContain("green");
    expect(coverageTone(80)).toContain("amber");
    expect(coverageTone(99)).toContain("amber");
    expect(coverageTone(50)).toContain("red");
    expect(coverageTone(0)).toContain("red");
  });

  it("shortItemCount: считает дефицитные позиции", () => {
    const items = [item({ status: "ok" }), item({ id: 2, status: "short" }), item({ id: 3, status: "short" })];
    expect(shortItemCount(items)).toBe(2);
    expect(shortItemCount([])).toBe(0);
  });

  it("bomCounts: всего/утверждено/черновики", () => {
    const boms = [
      bom({ id: 1, status: "approved" }),
      bom({ id: 2, status: "draft" }),
      bom({ id: 3, status: "draft" }),
    ];
    expect(bomCounts(boms)).toEqual({ total: 3, approved: 1, draft: 2 });
    expect(bomCounts([])).toEqual({ total: 0, approved: 0, draft: 0 });
  });
});
