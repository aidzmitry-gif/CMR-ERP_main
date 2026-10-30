import { afterEach, describe, expect, it, vi } from "vitest";

import {
  adjustment,
  type BalanceRow,
  createLocation,
  fetchBalances,
  fetchBalancesServer,
  fetchLocations,
  fetchLocation,
  fetchLocationOrganizations,
  fetchLocationWarehouses,
  LocationRequestError,
  fetchLocationsServer,
  fetchMovements,
  fetchMovementsServer,
  locationLabel,
  reasonLabel,
  shipment,
  type StockMovement,
  transfer,
  type WmsLocation,
} from "@/lib/wms-ops";

afterEach(() => vi.restoreAllMocks());

function stubFetch(data: unknown, ok = true) {
  const fn = vi.fn().mockResolvedValue({ ok, status: ok ? 200 : 503, json: async () => data });
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
  organization_id: 7,
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
  it("fetchBalancesServer forwards trusted identity headers", async () => {
    const fn = stubFetch({ rows: [], sku_count: 0 });
    const headers = { Authorization: "Bearer synthetic-test-only" };
    await fetchBalancesServer("admin", headers);
    expect(fn).toHaveBeenCalledWith("http://127.0.0.1:8000/wms/balances", { cache: "no-store", headers });
  });
  it("fetchLocationsServer forwards trusted identity headers", async () => {
    const fn = stubFetch([location]);
    const headers = { Authorization: "Bearer synthetic-test-only" };
    await fetchLocationsServer("admin", headers);
    expect(fn).toHaveBeenCalledWith("http://127.0.0.1:8000/wms/locations", {
      cache: "no-store", headers,
    });
  });
  it("fetchMovementsServer forwards trusted identity headers", async () => {
    const fn = stubFetch([movement]);
    const headers = { Authorization: "Bearer synthetic-test-only" };
    await fetchMovementsServer("admin", headers);
    expect(fn).toHaveBeenCalledWith("http://127.0.0.1:8000/wms/movements", {
      cache: "no-store", headers,
    });
  });
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

  it("fetchMovementsServer: HTTP failure rejects", async () => {
    stubFetch(null, false);
    await expect(fetchMovementsServer()).rejects.toThrow();
  });

  it("fetchMovementsServer: network failure rejects", async () => {
    stubFetchThrow();
    await expect(fetchMovementsServer()).rejects.toThrow();
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

  it("fetchBalancesServer: HTTP error rejects", async () => {
    stubFetch(null, false);
    await expect(fetchBalancesServer()).rejects.toThrow();
  });

  it("fetchBalancesServer: network error rejects", async () => {
    stubFetchThrow();
    await expect(fetchBalancesServer()).rejects.toThrow();
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

  it("fetchLocationsServer: HTTP failure rejects", async () => {
    stubFetch(null, false);
    await expect(fetchLocationsServer()).rejects.toThrow();
  });

  it("fetchLocationsServer: network failure rejects", async () => {
    stubFetchThrow();
    await expect(fetchLocationsServer()).rejects.toThrow();
  });
});

describe("клиентские fetch* через /api", () => {
  it("fetchMovements: URL /api/wms/movements, no-store, маппинг", async () => {
    const fn = stubFetch([movement]);
    const rows = await fetchMovements();
    expect(fn).toHaveBeenCalledWith("/api/wms/movements", { cache: "no-store" });
    expect(rows).toEqual([movement]);
  });

  it("fetchMovements: HTTP failure rejects", async () => {
    stubFetch(null, false);
    await expect(fetchMovements()).rejects.toThrow();
  });

  it("fetchMovements: network failure rejects", async () => {
    stubFetchThrow();
    await expect(fetchMovements()).rejects.toThrow();
  });

  it("fetchBalances: URL /api/wms/balances, маппинг", async () => {
    const data = { rows: [balanceRow], sku_count: 1 };
    const fn = stubFetch(data);
    const res = await fetchBalances();
    expect(fn).toHaveBeenCalledWith("/api/wms/balances", { cache: "no-store" });
    expect(res).toEqual(data);
  });

  it("fetchBalances: HTTP error rejects", async () => {
    stubFetch(null, false);
    await expect(fetchBalances()).rejects.toThrow();
  });

  it("fetchBalances: network error rejects", async () => {
    stubFetchThrow();
    await expect(fetchBalances()).rejects.toThrow();
  });

  it("fetchLocations: URL /api/wms/locations, маппинг", async () => {
    const fn = stubFetch([location]);
    const res = await fetchLocations();
    expect(fn).toHaveBeenCalledWith("/api/wms/locations", { cache: "no-store" });
    expect(res).toEqual([location]);
  });

  it("fetchLocations: HTTP failure rejects", async () => {
    stubFetch(null, false);
    await expect(fetchLocations()).rejects.toThrow();
  });

  it("fetchLocations: network failure rejects", async () => {
    stubFetchThrow();
    await expect(fetchLocations()).rejects.toThrow();
  });
});

describe("операции записи (POST /api/wms/*)", () => {
  const input = { organization_id: 7, sku_code: "AKB-60", qty: 5, warehouse: "Минск", location_id: 3, batch_ref: "B-1", note: "прим" };

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
      organization_id: 7,
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
    const locInput = { organization_id: 7, warehouse: "Минск", zone: "A", code: "A-02", title: "Стеллаж A-02" };
    const fn = stubFetch({ ...location, ...locInput });
    const result = await createLocation(locInput);
    expect(fn).toHaveBeenCalledWith("/api/wms/locations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(locInput),
    });
    expect(result).toEqual({ ...location, ...locInput });
  });

  it("createLocation: network failure has unknown result", async () => {
    stubFetchThrow();
    await expect(createLocation({ organization_id: 7, warehouse: "Минск", code: "A-03" })).rejects.toMatchObject({ resultUnknown: true });
  });
});


describe("owned locations", () => {
  it("sends an explicit company filter and refuses foreign response rows", async () => {
    const fn = stubFetch([location]);
    expect(await fetchLocations(7)).toEqual([location]);
    expect(fn).toHaveBeenCalledWith("/api/wms/locations?organization_id=7", { cache: "no-store" });
    stubFetch([{ ...location, organization_id: 8 }]);
    await expect(fetchLocations(7)).rejects.toThrow();
  });
  it("single location GET uses its id and only 404 means missing", async () => {
    const fn = stubFetch(location);
    expect(await fetchLocation(3)).toEqual(location);
    expect(fn).toHaveBeenCalledWith("/api/wms/locations/3", { cache: "no-store" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }));
    expect(await fetchLocation(3)).toBeNull();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 403 }));
    await expect(fetchLocation(3)).rejects.toMatchObject({ status: 403 });
  });
  it("rejects malformed ownership and mismatched label identity", async () => {
    stubFetch([{ ...location, organization_id: null }]);
    await expect(fetchLocations()).rejects.toThrow();
    stubFetch({ ...location, id: 4 });
    await expect(fetchLocation(3)).rejects.toThrow();
  });
  it("uses trusted server identity for company names and validates names", async () => {
    const headers = { Authorization: "Bearer synthetic-test-only" };
    const fn = stubFetch([{ id: 7, name: "Учебная компания" }]);
    expect(await fetchLocationOrganizations(headers)).toEqual([{ id: 7, name: "Учебная компания" }]);
    expect(fn).toHaveBeenCalledWith("http://127.0.0.1:8000/wms/receipt-organizations", { cache: "no-store", headers });
    stubFetch([{ id: 7, name: null }]);
    await expect(fetchLocationOrganizations()).rejects.toThrow();
  });
  it("searches registered warehouses and rejects a foreign catalogue", async () => {
    const data = { organization_id: 7, items: [{ organization_id: 7, name: "Главный" }], truncated: true };
    const fn = stubFetch(data);
    expect(await fetchLocationWarehouses(7, "  Главный  ")).toEqual({ items: data.items, truncated: true });
    expect(fn).toHaveBeenCalledWith(`/api/wms/organizations/7/warehouse-options?q=${encodeURIComponent("Главный")}`, { cache: "no-store" });
    stubFetch({ ...data, organization_id: 8 });
    await expect(fetchLocationWarehouses(7)).rejects.toThrow();
  });
  it("refuses a successful write response from another company without false success", async () => {
    stubFetch({ ...location, organization_id: 8 });
    await expect(createLocation({ organization_id: 7, warehouse: "Минск", code: "A-01" })).rejects.toMatchObject({ resultUnknown: true });
  });
  it("does not send absent company or warehouse and preserves known rejection status", async () => {
    const fn = stubFetch(location);
    await expect(createLocation({ organization_id: 0, warehouse: "Минск", code: "A" })).rejects.toThrow();
    await expect(createLocation({ organization_id: 7, warehouse: "", code: "A" })).rejects.toThrow();
    expect(fn).not.toHaveBeenCalled();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422 }));
    await expect(createLocation({ organization_id: 7, warehouse: "Минск", code: "A" })).rejects.toEqual(expect.objectContaining({ status: 422, resultUnknown: false }));
    expect(new LocationRequestError("x").resultUnknown).toBe(false);
  });
});
