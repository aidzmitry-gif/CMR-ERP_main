import { afterEach, describe, expect, it, vi } from "vitest";

import {
  addLine,
  deleteLine,
  emptyLine,
  fetchLandedPreview,
  fetchOrder,
  fetchOrderServer,
  updateFreight,
  type MachineOrder,
} from "@/lib/procurement-machine";

afterEach(() => vi.restoreAllMocks());

function stubFetch(data: unknown, ok = true) {
  const fn = vi.fn().mockResolvedValue({ ok, json: async () => data });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const order: MachineOrder = {
  id: 5,
  number: "ZAK-5",
  supplier: "ООО Поставщик",
  supplier_id: 3,
  status: "draft",
  eta_date: "2026-08-01",
  freight_byn: 100,
  lines: [
    { id: 1, sku_code: "SKU-1", qty: 2, goods_value_byn: 50, weight: 1.5, volume: 0.2 },
  ],
};

describe("emptyLine", () => {
  it("returns a blank line with qty 1 and zeroed money/weight/volume", () => {
    expect(emptyLine()).toEqual({ sku_code: "", qty: 1, goods_value_byn: 0, weight: 0, volume: 0 });
  });
});

describe("fetchOrderServer", () => {
  it("calls the backend BASE URL with cache no-store and returns parsed order", async () => {
    const fn = stubFetch(order);
    const result = await fetchOrderServer(5);
    expect(fn).toHaveBeenCalledWith("http://127.0.0.1:8000/procurement/orders/5", {
      cache: "no-store",
      headers: undefined,
    });
    expect(result).toEqual(order);
  });

  it("passes X-User-Roles header when roles provided", async () => {
    const fn = stubFetch(order);
    await fetchOrderServer(5, "procurement_head");
    expect(fn).toHaveBeenCalledWith("http://127.0.0.1:8000/procurement/orders/5", {
      cache: "no-store",
      headers: { "X-User-Roles": "procurement_head" },
    });
  });

  it("returns null on non-ok response", async () => {
    stubFetch({ error: "nope" }, false);
    expect(await fetchOrderServer(5)).toBeNull();
  });

  it("returns null when fetch throws", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    expect(await fetchOrderServer(5)).toBeNull();
  });
});

describe("fetchOrder", () => {
  it("calls the relative proxy URL and returns parsed order", async () => {
    const fn = stubFetch(order);
    const result = await fetchOrder(5);
    expect(fn).toHaveBeenCalledWith("/api/procurement/orders/5", { cache: "no-store" });
    expect(result).toEqual(order);
  });

  it("returns null on non-ok response", async () => {
    stubFetch(null, false);
    expect(await fetchOrder(5)).toBeNull();
  });

  it("returns null when fetch throws", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")));
    expect(await fetchOrder(5)).toBeNull();
  });
});

describe("fetchLandedPreview", () => {
  const preview = {
    order_id: 5,
    freight_byn: 100,
    lines: [
      { sku_code: "SKU-1", goods_byn: 50, allocated_byn: 20, landed_total_byn: 70, unit_landed_cost_byn: 35 },
    ],
    total_goods_byn: 50,
    total_landed_byn: 70,
  };

  it("calls the landed-preview endpoint and returns parsed data", async () => {
    const fn = stubFetch(preview);
    const result = await fetchLandedPreview(5);
    expect(fn).toHaveBeenCalledWith("/api/procurement/orders/5/landed-preview", { cache: "no-store" });
    expect(result).toEqual(preview);
  });

  it("returns null on non-ok response", async () => {
    stubFetch(null, false);
    expect(await fetchLandedPreview(5)).toBeNull();
  });

  it("returns null when fetch throws", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")));
    expect(await fetchLandedPreview(5)).toBeNull();
  });
});

describe("addLine", () => {
  const newLine = { sku_code: "SKU-2", qty: 3, goods_value_byn: 75, weight: 2, volume: 0.4 };

  it("POSTs the line as JSON to the lines endpoint and returns updated order", async () => {
    const fn = stubFetch(order);
    const result = await addLine(5, newLine);
    expect(fn).toHaveBeenCalledWith("/api/procurement/orders/5/lines", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(newLine),
    });
    expect(result).toEqual(order);
  });

  it("returns null on non-ok response", async () => {
    stubFetch(null, false);
    expect(await addLine(5, newLine)).toBeNull();
  });

  it("returns null when fetch throws", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")));
    expect(await addLine(5, newLine)).toBeNull();
  });
});

describe("deleteLine", () => {
  it("DELETEs the specific line URL and returns updated order", async () => {
    const fn = stubFetch(order);
    const result = await deleteLine(5, 1);
    expect(fn).toHaveBeenCalledWith("/api/procurement/orders/5/lines/1", { method: "DELETE" });
    expect(result).toEqual(order);
  });

  it("returns null on non-ok response", async () => {
    stubFetch(null, false);
    expect(await deleteLine(5, 1)).toBeNull();
  });

  it("returns null when fetch throws", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")));
    expect(await deleteLine(5, 1)).toBeNull();
  });
});

describe("updateFreight", () => {
  it("PATCHes freight_byn as JSON to the header endpoint and returns updated order", async () => {
    const fn = stubFetch(order);
    const result = await updateFreight(5, 250.5);
    expect(fn).toHaveBeenCalledWith("/api/procurement/orders/5/header", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ freight_byn: 250.5 }),
    });
    expect(result).toEqual(order);
  });

  it("returns null on non-ok response", async () => {
    stubFetch(null, false);
    expect(await updateFreight(5, 250.5)).toBeNull();
  });

  it("returns null when fetch throws", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")));
    expect(await updateFreight(5, 250.5)).toBeNull();
  });
});
