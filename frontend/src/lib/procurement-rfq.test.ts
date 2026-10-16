import { afterEach, describe, expect, it, vi } from "vitest";
import { addBid, awardRfq, bestBidId, createRfq, fetchRfqs, statusLabel, type Rfq, type RfqBid } from "@/lib/procurement-rfq";

afterEach(() => vi.restoreAllMocks());

const rfq: Rfq = { id: 5, number: "RFQ-000005", organization_id: 7, request_key: "key", request_id: 11,
  item: "Кабель", sku_code: "", qty: 10, status: "open", due_date: null,
  bids: [], best_bid_id: null };

function stub(data: unknown, ok = true) {
  const mock = vi.fn().mockResolvedValue({ ok, json: async () => data });
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("RFQ по юрлицу", () => {
  it("reads only a matching organization page and refuses a foreign response", async () => {
    const page = { organization_id: 7, items: [rfq], next_after_id: null };
    const fetch = stub(page);
    expect(await fetchRfqs(7)).toEqual(page);
    expect(fetch).toHaveBeenCalledWith("/api/procurement/organizations/7/rfq?after_id=0", { cache: "no-store" });
    stub({ ...page, organization_id: 8 });
    expect(await fetchRfqs(7)).toBeNull();
    stub({ ...page, items: [{ ...rfq, organization_id: 8 }] });
    expect(await fetchRfqs(7)).toBeNull();
  });

  it("sends an owned request and stable key for create", async () => {
    const fetch = stub(rfq);
    const body = { request_key: "4a21d982-2b6d-422b-9405-3868f0b210a1", request_id: 11 };
    expect(await createRfq(7, body)).toEqual(rfq);
    expect(fetch).toHaveBeenCalledWith("/api/procurement/organizations/7/rfq", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    stub({ ...rfq, organization_id: 8 });
    expect(await createRfq(7, body)).toBeNull();
  });

  it("sends exact decimal bid and an organization-scoped award", async () => {
    const fetch = stub(rfq);
    const bid = { bid_key: "4a21d982-2b6d-422b-9405-3868f0b210a2", supplier_id: 2,
      price_byn: "100.50", lead_time_days: 10 };
    expect(await addBid(7, 5, bid)).toEqual(rfq);
    expect(fetch).toHaveBeenCalledWith("/api/procurement/organizations/7/rfq/5/bids", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(bid),
    });
    expect(await awardRfq(7, 5, 3)).toEqual(rfq);
    expect(fetch).toHaveBeenLastCalledWith("/api/procurement/organizations/7/rfq/5/award", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ bid_id: 3 }),
    });
  });

  it("keeps pure score display behavior", () => {
    const bid = (id: number, price_byn: number): RfqBid => ({ id, rfq_id: 5, supplier_id: id,
      price_byn, lead_time_days: null, incoterms: "", note: "", is_winner: false });
    expect(bestBidId([bid(1, 120), bid(2, 90)])).toBe(2);
    expect(statusLabel("awarded")).toBe("Победитель выбран");
  });
});
