import { afterEach, describe, expect, it, vi } from "vitest";

import {
  daysToEta,
  fetchOpenOrders,
  fetchOpenOrdersServer,
  orderTotals,
  statusLabel,
  type OpenOrder,
} from "@/lib/procurement-orders";

afterEach(() => vi.unstubAllGlobals());

const orders: OpenOrder[] = [
  {
    id: 1,
    number: "PO-1",
    supplier: "Поставщик",
    status: "ordered",
    eta_date: "2026-09-20",
    freight_byn: 100,
    lines: [{ sku_code: "AKB", qty: 2, goods_value_byn: 500, weight: 1, volume: 1 }],
  },
  {
    id: 2,
    number: "PO-2",
    supplier: "Поставщик 2",
    status: "shipped",
    eta_date: null,
    freight_byn: 50,
    lines: [],
  },
];

describe("procurement-orders", () => {
  it("считает ETA, подписи статусов и итоговые суммы", () => {
    const now = Date.parse("2026-09-17T00:00:00Z");
    expect(daysToEta("2026-09-20T00:00:00Z", now)).toBe(3);
    expect(daysToEta(null, now)).toBeNull();
    expect(daysToEta("bad-date", now)).toBeNull();
    expect(statusLabel("ordered")).toBe("Заказан");
    expect(statusLabel("custom")).toBe("custom");
    expect(orderTotals(orders)).toEqual({ orders: 2, positions: 1, goods: 500, freight: 150 });
  });

  it("читает SSR/client endpoints и возвращает [] при HTTP/сетевой ошибке", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => orders });
    vi.stubGlobal("fetch", fetchMock);
    await expect(fetchOpenOrdersServer("sales")).resolves.toEqual(orders);
    await expect(fetchOpenOrders()).resolves.toEqual(orders);
    expect(fetchMock).toHaveBeenNthCalledWith(1, expect.stringContaining("/procurement/open-orders"), expect.objectContaining({ headers: { "X-User-Roles": "sales" } }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
    await expect(fetchOpenOrdersServer()).resolves.toEqual([]);
    await expect(fetchOpenOrders()).resolves.toEqual([]);
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    await expect(fetchOpenOrdersServer()).resolves.toEqual([]);
    await expect(fetchOpenOrders()).resolves.toEqual([]);
  });
});
