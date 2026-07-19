import { afterEach, describe, expect, it, vi } from "vitest";

import {
  adjustment,
  type BalanceRow,
  createLocation,
  fetchBalances,
  fetchBalancesServer,
  fetchLocations,
  fetchLocationsServer,
  fetchMovements,
  fetchMovementsServer,
  locationLabel,
  reasonLabel,
  receipt,
  shipment,
  type StockMovement,
  transfer,
  type WmsLocation,
} from "@/lib/wms-ops";

afterEach(() => vi.restoreAllMocks());

function stubFetch(data: unknown, ok = true) {
  const fn = vi.fn().mockResolvedValue({ ok, json: async () => data });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function stubFetchThrow() {
  const fn = vi.fn().mockRejectedValue(new Error("network down"));
  vi.stubGlobal("fetch", fn);
  return fn;
}

const movement: StockMovement = {
  id: 1,
  sku_code: "AKB-60",
  warehouse: "Минск",
  kind: "in",
  qty: 5,
  reason: "receipt",
  location_id: 3,
  batch_ref: "B-1",
  doc_ref: "D-1",
  note: "",
  created_at: "2026-07-19T00:00:00Z",
};

const location: WmsLocation = {
  id: 3,
  warehouse: "Минск",
  zone: "A",
  code: "A-01",
  title: "Стеллаж A-01",
  is_active: true,
};

const balanceRow: BalanceRow = {
  sku_code: "AKB-60",
  sku_title: "Аккумулятор 60 Ач",
  warehouse: "Минск",
  location_id: 3,
  location_code: "A-01",
  batch_ref: "B-1",
  qty: 12,
};

describe("reasonLabel", () => {
  it("переводит причины движения", () => {
    expect(reasonLabel("receipt")).toBe("Приёмка");
    expect(reasonLabel("shipment")).toBe("Отгрузка");
    expect(reasonLabel("transfer")).toBe("Перемещение");
    expect(reasonLabel("adjustment")).toBe("Коррекция");
    expect(reasonLabel("release")).toBe("Снятие резерва");
  });
  it("пустая строка возвращает «—»", () => {
    expect(reasonLabel("")).toBe("—");
  });
  it("неизвестная причина возвращается как есть", () => {
    expect(reasonLabel("weird")).toBe("weird");
  });
});

describe("locationLabel", () => {
  it("зона + код", () => {
    expect(locationLabel({ zone: "A", code: "A-01" })).toBe("A · A-01");
  });
  it("только код", () => {
    expect(locationLabel({ zone: "", code: "A-01" })).toBe("A-01");
  });
  it("нет кода → тире", () => {
    expect(locationLabel({ zone: "A", code: "" })).toBe("—");
  });
});

describe("SSR fetch*Server", () => {
  it("fetchMovementsServer: URL, no-store, роли в заголовке, маппинг ответа", async () => {
    const fn = stubFetch([movement]);
    const rows = await fetchMovementsServer("sales,admin");
    expect(fn).toHaveBeenCalledWith("http://127.0.0.1:8000/wms/movements", {
      cache: "no-store",
      headers: { "X-User-Roles": "sales,admin" },
    });
    expect(rows).toEqual([movement]);
  });

  it("fetchMovementsServer: без ролей — заголовков нет", async () => {
    const fn = stubFetch([movement]);
    await fetchMovementsServer();
    expect(fn).toHaveBeenCalledWith("http://127.0.0.1:8000/wms/movements", {
      cache: "no-store",
      headers: undefined,
    });
  });

  it("fetchMovementsServer: ok:false → пустой массив", async () => {
    stubFetch(null, false);
    expect(await fetchMovementsServer()).toEqual([]);
  });

  it("fetchMovementsServer: сеть упала → пустой массив", async () => {
    stubFetchThrow();
    expect(await fetchMovementsServer()).toEqual([]);
  });

  it("fetchBalancesServer: URL и маппинг", async () => {
    const data = { rows: [balanceRow], sku_count: 1 };
    const fn = stubFetch(data);
    const res = await fetchBalancesServer("rop");
    expect(fn).toHaveBeenCalledWith("http://127.0.0.1:8000/wms/balances", {
      cache: "no-store",
      headers: { "X-User-Roles": "rop" },
    });
    expect(res).toEqual(data);
  });

  it("fetchBalancesServer: ok:false → пустой дефолт с sku_count 0", async () => {
    stubFetch(null, false);
    expect(await fetchBalancesServer()).toEqual({ rows: [], sku_count: 0 });
  });

  it("fetchBalancesServer: сеть упала → пустой дефолт", async () => {
    stubFetchThrow();
    expect(await fetchBalancesServer()).toEqual({ rows: [], sku_count: 0 });
  });

  it("fetchLocationsServer: URL и маппинг", async () => {
    const fn = stubFetch([location]);
    const res = await fetchLocationsServer("admin");
    expect(fn).toHaveBeenCalledWith("http://127.0.0.1:8000/wms/locations", {
      cache: "no-store",
      headers: { "X-User-Roles": "admin" },
    });
    expect(res).toEqual([location]);
  });

  it("fetchLocationsServer: ok:false → пустой массив", async () => {
    stubFetch(null, false);
    expect(await fetchLocationsServer()).toEqual([]);
  });

  it("fetchLocationsServer: сеть упала → пустой массив", async () => {
    stubFetchThrow();
    expect(await fetchLocationsServer()).toEqual([]);
  });
});

describe("клиентские fetch* через /api", () => {
  it("fetchMovements: URL /api/wms/movements, no-store, маппинг", async () => {
    const fn = stubFetch([movement]);
    const rows = await fetchMovements();
    expect(fn).toHaveBeenCalledWith("/api/wms/movements", { cache: "no-store" });
    expect(rows).toEqual([movement]);
  });

  it("fetchMovements: ok:false → пустой массив", async () => {
    stubFetch(null, false);
    expect(await fetchMovements()).toEqual([]);
  });

  it("fetchMovements: сеть упала → пустой массив", async () => {
    stubFetchThrow();
    expect(await fetchMovements()).toEqual([]);
  });

  it("fetchBalances: URL /api/wms/balances, маппинг", async () => {
    const data = { rows: [balanceRow], sku_count: 1 };
    const fn = stubFetch(data);
    const res = await fetchBalances();
    expect(fn).toHaveBeenCalledWith("/api/wms/balances", { cache: "no-store" });
    expect(res).toEqual(data);
  });

  it("fetchBalances: ok:false → пустой дефолт", async () => {
    stubFetch(null, false);
    expect(await fetchBalances()).toEqual({ rows: [], sku_count: 0 });
  });

  it("fetchBalances: сеть упала → пустой дефолт", async () => {
    stubFetchThrow();
    expect(await fetchBalances()).toEqual({ rows: [], sku_count: 0 });
  });

  it("fetchLocations: URL /api/wms/locations, маппинг", async () => {
    const fn = stubFetch([location]);
    const res = await fetchLocations();
    expect(fn).toHaveBeenCalledWith("/api/wms/locations", { cache: "no-store" });
    expect(res).toEqual([location]);
  });

  it("fetchLocations: ok:false → пустой массив", async () => {
    stubFetch(null, false);
    expect(await fetchLocations()).toEqual([]);
  });

  it("fetchLocations: сеть упала → пустой массив", async () => {
    stubFetchThrow();
    expect(await fetchLocations()).toEqual([]);
  });
});

describe("операции записи (POST /api/wms/*)", () => {
  const input = { sku_code: "AKB-60", qty: 5, warehouse: "Минск", location_id: 3, batch_ref: "B-1", note: "прим" };

  it("receipt: URL, метод, заголовки, тело — true при ok", async () => {
    const fn = stubFetch({ ok: true });
    const result = await receipt(input);
    expect(fn).toHaveBeenCalledWith("/api/wms/receipt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    expect(result).toBe(true);
  });

  it("receipt: ok:false → false", async () => {
    stubFetch(null, false);
    expect(await receipt(input)).toBe(false);
  });

  it("receipt: сеть упала → false", async () => {
    stubFetchThrow();
    expect(await receipt(input)).toBe(false);
  });

  it("shipment: правильный путь /api/wms/shipment", async () => {
    const fn = stubFetch({});
    await shipment(input);
    expect(fn).toHaveBeenCalledWith(
      "/api/wms/shipment",
      expect.objectContaining({ method: "POST", body: JSON.stringify(input) }),
    );
  });

  it("adjustment: правильный путь /api/wms/adjustment", async () => {
    const fn = stubFetch({});
    await adjustment(input);
    expect(fn).toHaveBeenCalledWith(
      "/api/wms/adjustment",
      expect.objectContaining({ method: "POST", body: JSON.stringify(input) }),
    );
  });

  it("transfer: путь /api/wms/transfer, тело с from/to", async () => {
    const transferInput = {
      sku_code: "AKB-60",
      qty: 2,
      warehouse: "Минск",
      from_location_id: 3,
      to_location_id: 4,
      batch_ref: "B-1",
      note: "",
    };
    const fn = stubFetch({});
    const result = await transfer(transferInput);
    expect(fn).toHaveBeenCalledWith("/api/wms/transfer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(transferInput),
    });
    expect(result).toBe(true);
  });

  it("createLocation: путь /api/wms/locations, тело", async () => {
    const locInput = { warehouse: "Минск", zone: "A", code: "A-02", title: "Стеллаж A-02" };
    const fn = stubFetch({});
    const result = await createLocation(locInput);
    expect(fn).toHaveBeenCalledWith("/api/wms/locations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(locInput),
    });
    expect(result).toBe(true);
  });

  it("createLocation: сеть упала → false", async () => {
    stubFetchThrow();
    expect(await createLocation({ warehouse: "Минск", code: "A-03" })).toBe(false);
  });
});
