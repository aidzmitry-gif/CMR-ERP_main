import { afterEach, describe, expect, it, vi } from "vitest";

import {
  addInventoryLine,
  completeInventory,
  createInventory,
  fetchInventoryDetail,
  fetchInventoryDetailServer,
  fetchInventoryListServer,
  inventoryStatusLabel,
  populateInventory,
  updateInventoryLine,
  varianceTone,
} from "@/lib/wms-inventory";

describe("inventoryStatusLabel", () => {
  it("переводит статусы документа", () => {
    expect(inventoryStatusLabel("open")).toBe("Идёт пересчёт");
    expect(inventoryStatusLabel("done")).toBe("Проведена");
    expect(inventoryStatusLabel("canceled")).toBe("Отменена");
  });

  it("неизвестный статус возвращает как есть", () => {
    expect(inventoryStatusLabel("weird" as never)).toBe("weird");
  });
});

describe("varianceTone", () => {
  it("нет факта → none", () => {
    expect(varianceTone(null)).toBe("none");
  });
  it("совпало → ok", () => {
    expect(varianceTone(0)).toBe("ok");
  });
  it("недостача → short, излишек → over", () => {
    expect(varianceTone(-3)).toBe("short");
    expect(varianceTone(2)).toBe("over");
  });
});

afterEach(() => vi.restoreAllMocks());

function mockFetch(impl: (...args: unknown[]) => Promise<unknown>) {
  global.fetch = vi.fn(impl) as unknown as typeof fetch;
}

const sampleCount = {
  id: 1,
  number: "ИНВ-1",
  warehouse: "Минск",
  status: "open",
  note: "",
  created_at: "2026-07-18T00:00:00Z",
  completed_at: null,
};

const sampleDetail = {
  ...sampleCount,
  lines: [
    {
      id: 10,
      sku_code: "SKU-1",
      sku_title: "Товар",
      unit: "шт",
      expected_qty: 5,
      counted_qty: 4,
      unit_cost: 100,
      variance: -1,
      variance_value: -100,
      note: "",
    },
  ],
  summary: {
    lines: 1,
    counted: 1,
    shortages: 1,
    surpluses: 0,
    shortage_value: 100,
    surplus_value: 0,
    net_value: -100,
  },
};

describe("fetchInventoryListServer", () => {
  it("возвращает список при 200 и шлёт роль-заголовок на абсолютный BACKEND_URL", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => [sampleCount] }));
    mockFetch(f);
    const result = await fetchInventoryListServer("sales_head");
    expect(result).toEqual([sampleCount]);
    expect(f).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/wms/inventory",
      expect.objectContaining({
        cache: "no-store",
        headers: { "X-User-Roles": "sales_head" },
      }),
    );
  });

  it("без ролей заголовок не передаётся", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => [] }));
    mockFetch(f);
    await fetchInventoryListServer();
    expect(f).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/wms/inventory",
      expect.objectContaining({ headers: undefined }),
    );
  });

  it("при HTTP-ошибке → []", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchInventoryListServer()).toEqual([]);
  });

  it("при исключении сети → []", async () => {
    mockFetch(async () => {
      throw new Error("net");
    });
    expect(await fetchInventoryListServer()).toEqual([]);
  });
});

describe("fetchInventoryDetailServer", () => {
  it("возвращает detail при 200 с корректным URL и ролью", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => sampleDetail }));
    mockFetch(f);
    const result = await fetchInventoryDetailServer("5", "wms_lead");
    expect(result).toEqual(sampleDetail);
    expect(f).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/wms/inventory/5",
      expect.objectContaining({
        cache: "no-store",
        headers: { "X-User-Roles": "wms_lead" },
      }),
    );
  });

  it("при HTTP-ошибке → null", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchInventoryDetailServer("5")).toBeNull();
  });

  it("при исключении сети → null", async () => {
    mockFetch(async () => {
      throw new Error("net");
    });
    expect(await fetchInventoryDetailServer("5")).toBeNull();
  });
});

describe("createInventory", () => {
  it("шлёт POST на /api/wms/inventory с warehouse и note", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => sampleCount }));
    mockFetch(f);
    const result = await createInventory("Минск", "плановая");
    expect(result).toEqual(sampleCount);
    expect(f).toHaveBeenCalledWith("/api/wms/inventory", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ warehouse: "Минск", note: "плановая" }),
    });
  });

  it("note по умолчанию — пустая строка", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => sampleCount }));
    mockFetch(f);
    await createInventory("Минск");
    expect(f).toHaveBeenCalledWith(
      "/api/wms/inventory",
      expect.objectContaining({ body: JSON.stringify({ warehouse: "Минск", note: "" }) }),
    );
  });

  it("при HTTP-ошибке → null", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await createInventory("Минск")).toBeNull();
  });

  it("при исключении сети → null", async () => {
    mockFetch(async () => {
      throw new Error("net");
    });
    expect(await createInventory("Минск")).toBeNull();
  });
});

describe("fetchInventoryDetail (клиент)", () => {
  it("возвращает detail при 200 по правильному URL", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => sampleDetail }));
    mockFetch(f);
    const result = await fetchInventoryDetail(5);
    expect(result).toEqual(sampleDetail);
    expect(f).toHaveBeenCalledWith("/api/wms/inventory/5", { cache: "no-store" });
  });

  it("при HTTP-ошибке → null", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchInventoryDetail(5)).toBeNull();
  });

  it("при исключении сети → null", async () => {
    mockFetch(async () => {
      throw new Error("net");
    });
    expect(await fetchInventoryDetail(5)).toBeNull();
  });
});

describe("populateInventory", () => {
  it("шлёт POST на /populate и возвращает обновлённый detail", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => sampleDetail }));
    mockFetch(f);
    const result = await populateInventory(5);
    expect(result).toEqual(sampleDetail);
    expect(f).toHaveBeenCalledWith("/api/wms/inventory/5/populate", { method: "POST" });
  });

  it("при HTTP-ошибке → null", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await populateInventory(5)).toBeNull();
  });

  it("при исключении сети → null", async () => {
    mockFetch(async () => {
      throw new Error("net");
    });
    expect(await populateInventory(5)).toBeNull();
  });
});

describe("updateInventoryLine", () => {
  it("шлёт PATCH с телом patch на /lines/{id} и возвращает res.ok", async () => {
    const f = vi.fn(async () => ({ ok: true }));
    mockFetch(f);
    const result = await updateInventoryLine(10, { counted_qty: 3, note: "пересчитано" });
    expect(result).toBe(true);
    expect(f).toHaveBeenCalledWith("/api/wms/inventory/lines/10", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ counted_qty: 3, note: "пересчитано" }),
    });
  });

  it("при ok:false → false", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await updateInventoryLine(10, { counted_qty: null })).toBe(false);
  });

  it("при исключении сети → false", async () => {
    mockFetch(async () => {
      throw new Error("net");
    });
    expect(await updateInventoryLine(10, { note: "x" })).toBe(false);
  });
});

describe("addInventoryLine", () => {
  it("шлёт POST c sku_code и counted_qty на /{id}/lines", async () => {
    const f = vi.fn(async () => ({ ok: true }));
    mockFetch(f);
    const result = await addInventoryLine(5, "SKU-9", 7);
    expect(result).toBe(true);
    expect(f).toHaveBeenCalledWith("/api/wms/inventory/5/lines", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sku_code: "SKU-9", counted_qty: 7 }),
    });
  });

  it("без counted_qty шлёт null по умолчанию", async () => {
    const f = vi.fn(async () => ({ ok: true }));
    mockFetch(f);
    await addInventoryLine(5, "SKU-9");
    expect(f).toHaveBeenCalledWith(
      "/api/wms/inventory/5/lines",
      expect.objectContaining({
        body: JSON.stringify({ sku_code: "SKU-9", counted_qty: null }),
      }),
    );
  });

  it("при ok:false → false", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await addInventoryLine(5, "SKU-9")).toBe(false);
  });

  it("при исключении сети → false", async () => {
    mockFetch(async () => {
      throw new Error("net");
    });
    expect(await addInventoryLine(5, "SKU-9")).toBe(false);
  });
});

describe("completeInventory", () => {
  it("шлёт POST на /complete и возвращает res.ok", async () => {
    const f = vi.fn(async () => ({ ok: true }));
    mockFetch(f);
    const result = await completeInventory(5);
    expect(result).toBe(true);
    expect(f).toHaveBeenCalledWith("/api/wms/inventory/5/complete", { method: "POST" });
  });

  it("при ok:false → false", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await completeInventory(5)).toBe(false);
  });

  it("при исключении сети → false", async () => {
    mockFetch(async () => {
      throw new Error("net");
    });
    expect(await completeInventory(5)).toBe(false);
  });
});
