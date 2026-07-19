import { afterEach, describe, expect, it, vi } from "vitest";

import {
  addBid,
  awardRfq,
  bestBidId,
  createRfq,
  fetchRfqs,
  fetchRfqsServer,
  statusLabel,
  type Rfq,
  type RfqBid,
} from "@/lib/procurement-rfq";

afterEach(() => vi.restoreAllMocks());

function stubFetch(data: unknown, ok = true) {
  const fn = vi.fn().mockResolvedValue({ ok, json: async () => data });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const rfq: Rfq = {
  id: 5,
  item: "Кабель ВВГ",
  sku_code: "SKU-1",
  qty: 100,
  request_id: null,
  status: "open",
  due_date: null,
  bids: [],
  best_bid_id: null,
};

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

describe("fetchRfqsServer", () => {
  it("дёргает бэкенд напрямую с ролями в заголовке", async () => {
    const fn = stubFetch([rfq]);
    const result = await fetchRfqsServer("sales_head");
    expect(fn).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/procurement/rfq",
      { cache: "no-store", headers: { "X-User-Roles": "sales_head" } },
    );
    expect(result).toEqual([rfq]);
  });

  it("без ролей — заголовков нет", async () => {
    const fn = stubFetch([rfq]);
    await fetchRfqsServer();
    expect(fn).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/procurement/rfq",
      { cache: "no-store", headers: undefined },
    );
  });

  it("ok:false → пустой массив", async () => {
    stubFetch(null, false);
    expect(await fetchRfqsServer()).toEqual([]);
  });

  it("сетевая ошибка → пустой массив", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await fetchRfqsServer()).toEqual([]);
  });
});

describe("fetchRfqs", () => {
  it("зовёт прокси-эндпоинт и возвращает список", async () => {
    const fn = stubFetch([rfq]);
    const result = await fetchRfqs();
    expect(fn).toHaveBeenCalledWith("/api/procurement/rfq", { cache: "no-store" });
    expect(result).toEqual([rfq]);
  });

  it("ok:false → null (не затирать SSR-данные пустым списком)", async () => {
    stubFetch(null, false);
    expect(await fetchRfqs()).toBeNull();
  });

  it("сетевая ошибка → null", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await fetchRfqs()).toBeNull();
  });
});

describe("createRfq", () => {
  it("POST с JSON-телом полей формы", async () => {
    const fn = stubFetch(rfq);
    const result = await createRfq({ item: "Кабель ВВГ", sku_code: "SKU-1", qty: 100 });
    expect(fn).toHaveBeenCalledWith("/api/procurement/rfq", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item: "Кабель ВВГ", sku_code: "SKU-1", qty: 100 }),
    });
    expect(result).toEqual(rfq);
  });

  it("ok:false → null", async () => {
    stubFetch(null, false);
    expect(await createRfq({ item: "x" })).toBeNull();
  });

  it("сетевая ошибка → null", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await createRfq({ item: "x" })).toBeNull();
  });
});

describe("addBid", () => {
  it("POST по /bids с телом предложения", async () => {
    const fn = stubFetch(rfq);
    const bid = { supplier_id: 7, price_byn: 950, lead_time_days: 14, incoterms: "FOB", note: "срочно" };
    const result = await addBid(5, bid);
    expect(fn).toHaveBeenCalledWith("/api/procurement/rfq/5/bids", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bid),
    });
    expect(result).toEqual(rfq);
  });

  it("ok:false → null", async () => {
    stubFetch(null, false);
    expect(await addBid(5, { price_byn: 100 })).toBeNull();
  });

  it("сетевая ошибка → null", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await addBid(5, { price_byn: 100 })).toBeNull();
  });
});

describe("awardRfq", () => {
  it("POST по /award с bid_id в теле", async () => {
    const fn = stubFetch({ ...rfq, status: "awarded", best_bid_id: 3 });
    const result = await awardRfq(5, 3);
    expect(fn).toHaveBeenCalledWith("/api/procurement/rfq/5/award", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bid_id: 3 }),
    });
    expect(result).toEqual({ ...rfq, status: "awarded", best_bid_id: 3 });
  });

  it("ok:false → null", async () => {
    stubFetch(null, false);
    expect(await awardRfq(5, 3)).toBeNull();
  });

  it("сетевая ошибка → null", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await awardRfq(5, 3)).toBeNull();
  });
});
