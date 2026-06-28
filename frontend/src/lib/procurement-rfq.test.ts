import { describe, expect, it } from "vitest";

import { bestBidId, statusLabel, type RfqBid } from "@/lib/procurement-rfq";

const B = (id: number, price: number): RfqBid => ({
  id,
  rfq_id: 1,
  supplier_id: id,
  price_byn: price,
  lead_time_days: null,
  incoterms: "",
  note: "",
  is_winner: false,
});

describe("statusLabel", () => {
  it("переводит статусы RFQ", () => {
    expect(statusLabel("open")).toBe("Открыт");
    expect(statusLabel("awarded")).toBe("Победитель выбран");
    expect(statusLabel("zzz")).toBe("zzz");
  });
});

describe("bestBidId", () => {
  it("минимальная цена — лучшая", () => {
    expect(bestBidId([B(1, 1200), B(2, 950), B(3, 1100)])).toBe(2);
  });
  it("пусто → null", () => {
    expect(bestBidId([])).toBeNull();
  });
});
