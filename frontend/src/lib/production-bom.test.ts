import { afterEach, describe, expect, it, vi } from "vitest";

import {
  addBomItem,
  approveBom,
  available,
  type Bom,
  bomCounts,
  type BomDetail,
  bomStatusLabel,
  type BomItem,
  coverageTone,
  createBom,
  deleteBom,
  deleteBomItem,
  fetchBom,
  fetchBoms,
  fetchBomsServer,
  itemStatusLabel,
  shortItemCount,
  updateBom,
  updateBomItem,
} from "@/lib/production-bom";

afterEach(() => vi.restoreAllMocks());

function stubFetch(data: unknown, ok = true) {
  const fn = vi.fn().mockResolvedValue({ ok, json: async () => data });
  vi.stubGlobal("fetch", fn);
  return fn;
}

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

  it("fetchBomsServer: ходит на BACKEND_URL, шлёт роли заголовком, маппит ответ", async () => {
    const data = [bom({ id: 7 })];
    const fn = stubFetch(data);
    const result = await fetchBomsServer("production_head");
    expect(fn).toHaveBeenCalledWith("http://127.0.0.1:8000/production/boms", {
      cache: "no-store",
      headers: { "X-User-Roles": "production_head" },
    });
    expect(result).toEqual(data);
  });

  it("fetchBomsServer: без ролей — заголовков нет; !ok → []; исключение → []", async () => {
    const fn = stubFetch([bom()]);
    await fetchBomsServer();
    expect(fn).toHaveBeenCalledWith("http://127.0.0.1:8000/production/boms", {
      cache: "no-store",
      headers: undefined,
    });

    stubFetch(null, false);
    expect(await fetchBomsServer()).toEqual([]);

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await fetchBomsServer()).toEqual([]);
  });

  it("fetchBoms: клиентский путь через /api, !ok → [], исключение → []", async () => {
    const data = [bom({ id: 2 })];
    const fn = stubFetch(data);
    expect(await fetchBoms()).toEqual(data);
    expect(fn).toHaveBeenCalledWith("/api/production/boms", { cache: "no-store" });

    stubFetch(null, false);
    expect(await fetchBoms()).toEqual([]);

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await fetchBoms()).toEqual([]);
  });

  it("fetchBom: подставляет id в URL, маппит BomDetail; !ok → null; исключение → null", async () => {
    const detail: BomDetail = { ...bom({ id: 9 }), items: [item()] };
    const fn = stubFetch(detail);
    const result = await fetchBom(9);
    expect(fn).toHaveBeenCalledWith("/api/production/boms/9", { cache: "no-store" });
    expect(result).toEqual(detail);

    stubFetch(null, false);
    expect(await fetchBom(9)).toBeNull();

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await fetchBom(9)).toBeNull();
  });

  it("createBom: POST с JSON-телом входа; !ok → null; исключение → null", async () => {
    const created = bom({ id: 11, product: "Шкаф ШРС" });
    const fn = stubFetch(created);
    const input = { product: "Шкаф ШРС", version: "v2", note: "прим" };
    const result = await createBom(input);
    expect(fn).toHaveBeenCalledWith("/api/production/boms", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    expect(result).toEqual(created);

    stubFetch(null, false);
    expect(await createBom(input)).toBeNull();

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await createBom(input)).toBeNull();
  });

  it("updateBom: PATCH по id с частичным патчем; !ok → null; исключение → null", async () => {
    const updated = bom({ id: 3, note: "новое" });
    const fn = stubFetch(updated);
    const patch = { note: "новое" };
    const result = await updateBom(3, patch);
    expect(fn).toHaveBeenCalledWith("/api/production/boms/3", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    expect(result).toEqual(updated);

    stubFetch(null, false);
    expect(await updateBom(3, patch)).toBeNull();

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await updateBom(3, patch)).toBeNull();
  });

  it("approveBom: POST на /approve, возвращает res.ok; исключение → false", async () => {
    const fn = stubFetch(null, true);
    expect(await approveBom(4)).toBe(true);
    expect(fn).toHaveBeenCalledWith("/api/production/boms/4/approve", { method: "POST" });

    stubFetch(null, false);
    expect(await approveBom(4)).toBe(false);

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await approveBom(4)).toBe(false);
  });

  it("deleteBom: DELETE по id, возвращает res.ok; исключение → false", async () => {
    const fn = stubFetch(null, true);
    expect(await deleteBom(5)).toBe(true);
    expect(fn).toHaveBeenCalledWith("/api/production/boms/5", { method: "DELETE" });

    stubFetch(null, false);
    expect(await deleteBom(5)).toBe(false);

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await deleteBom(5)).toBe(false);
  });

  it("addBomItem: POST состав в bomId/items с телом; исключение → false", async () => {
    const fn = stubFetch(null, true);
    const input = { component: "BMS 16S", norm_qty: 2, unit: "шт" };
    expect(await addBomItem(6, input)).toBe(true);
    expect(fn).toHaveBeenCalledWith("/api/production/boms/6/items", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });

    stubFetch(null, false);
    expect(await addBomItem(6, input)).toBe(false);

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await addBomItem(6, input)).toBe(false);
  });

  it("updateBomItem: PATCH позиции по id с патчем; исключение → false", async () => {
    const fn = stubFetch(null, true);
    const patch = { stock: 20 };
    expect(await updateBomItem(12, patch)).toBe(true);
    expect(fn).toHaveBeenCalledWith("/api/production/bom-items/12", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });

    stubFetch(null, false);
    expect(await updateBomItem(12, patch)).toBe(false);

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await updateBomItem(12, patch)).toBe(false);
  });

  it("deleteBomItem: DELETE позиции по id; исключение → false", async () => {
    const fn = stubFetch(null, true);
    expect(await deleteBomItem(13)).toBe(true);
    expect(fn).toHaveBeenCalledWith("/api/production/bom-items/13", { method: "DELETE" });

    stubFetch(null, false);
    expect(await deleteBomItem(13)).toBe(false);

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await deleteBomItem(13)).toBe(false);
  });
});
