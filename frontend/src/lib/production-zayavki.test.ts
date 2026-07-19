import { afterEach, describe, expect, it, vi } from "vitest";

import { type Bom } from "@/lib/production-bom";
import { type Norm } from "@/lib/production-norms";
import {
  coverageForProduct,
  createOrder,
  fetchOrders,
  fetchOrdersServer,
  nhTotal,
  normForProduct,
  type Order,
  stageLabel,
  stageTone,
  updateOrderStage,
  zayavkiCounts,
} from "@/lib/production-zayavki";

afterEach(() => vi.restoreAllMocks());

function stubFetch(data: unknown, ok = true) {
  const fn = vi.fn().mockResolvedValue({ ok, json: async () => data });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function order(over: Partial<Order> = {}): Order {
  return {
    id: 1,
    number: "ПЗ-2026-0001",
    product: "АКБ 48V 100Ah",
    qty: 4,
    progress: 0,
    priority: "Средний",
    owner: "Мастер",
    stage: "queue",
    due_date: null,
    insight: "",
    nh_per_unit: 7.5,
    made_qty: 0,
    ...over,
  };
}

function norm(over: Partial<Norm> = {}): Norm {
  return { id: 1, kind: "product", title: "АКБ 48V 100Ah", nh: 7.5, status: "approved", note: "", ...over };
}

function bom(over: Partial<Bom> = {}): Bom {
  return {
    id: 1,
    product: "АКБ 48V 100Ah",
    version: "v1",
    status: "approved",
    note: "",
    item_count: 3,
    coverage: 80,
    ...over,
  };
}

describe("production-zayavki", () => {
  it("stageLabel: человекочитаемые этапы заявки", () => {
    expect(stageLabel("queue")).toBe("Новая · очередь");
    expect(stageLabel("assembly")).toBe("В работе");
    expect(stageLabel("done")).toBe("Готово");
    expect(stageLabel("неведомо")).toBe("неведомо"); // неизвестный этап — как есть
  });

  it("normForProduct: только утверждённая норма по точному названию", () => {
    const norms = [norm({ status: "pending" }), norm({ id: 2, status: "approved" })];
    expect(normForProduct(norms, "АКБ 48V 100Ah")?.id).toBe(2);
    expect(normForProduct(norms, "Другое изделие")).toBeNull();
    expect(normForProduct([norm({ status: "pending" })], "АКБ 48V 100Ah")).toBeNull();
  });

  it("coverageForProduct: обеспеченность из BOM по названию или null", () => {
    const boms = [bom({ coverage: 80 })];
    expect(coverageForProduct(boms, "АКБ 48V 100Ah")).toBe(80);
    expect(coverageForProduct(boms, "Нет такого")).toBeNull();
    expect(coverageForProduct([], "АКБ 48V 100Ah")).toBeNull();
  });

  it("nhTotal: норма/шт × количество", () => {
    expect(nhTotal({ nh_per_unit: 7.5, qty: 4 })).toBe(30);
    expect(nhTotal({ nh_per_unit: 0, qty: 4 })).toBe(0);
  });

  it("zayavkiCounts: всего/без нормы/без BOM/в работе", () => {
    const orders = [
      order({ id: 1, product: "АКБ 48V 100Ah", stage: "queue" }), // норма+BOM есть, очередь
      order({ id: 2, product: "Шкаф ШРС", stage: "assembly" }), // нормы/BOM нет, в работе
      order({ id: 3, product: "АКБ 48V 100Ah", stage: "done" }), // готово
    ];
    const counts = zayavkiCounts(orders, [norm()], [bom()]);
    expect(counts.total).toBe(3);
    expect(counts.withoutNorm).toBe(1); // только «Шкаф ШРС»
    expect(counts.withoutBom).toBe(1);
    expect(counts.inProgress).toBe(1); // только assembly (queue и done не в работе)
  });

  it("stageTone: тон по этапу, неизвестный — дефолт", () => {
    expect(stageTone("queue")).toBe("bg-slate-100 text-slate-500");
    expect(stageTone("assembly")).toBe("bg-amber-50 text-amber-600");
    expect(stageTone("done")).toBe("bg-green-50 text-green-600");
    expect(stageTone("неведомо")).toBe("bg-slate-100 text-slate-500");
  });

  it("fetchOrdersServer: ходит на BACKEND_URL, шлёт роли заголовком, маппит ответ; без ролей — заголовков нет", async () => {
    const data = [order({ id: 7 })];
    const fn = stubFetch(data);
    const result = await fetchOrdersServer("production_head");
    expect(fn).toHaveBeenCalledWith("http://127.0.0.1:8000/production/orders", {
      cache: "no-store",
      headers: { "X-User-Roles": "production_head" },
    });
    expect(result).toEqual(data);

    const fn2 = stubFetch(data);
    await fetchOrdersServer();
    expect(fn2).toHaveBeenCalledWith("http://127.0.0.1:8000/production/orders", {
      cache: "no-store",
      headers: undefined,
    });
  });

  it("fetchOrdersServer: !ok → []; исключение → []", async () => {
    stubFetch(null, false);
    expect(await fetchOrdersServer()).toEqual([]);

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await fetchOrdersServer()).toEqual([]);
  });

  it("fetchOrders: клиентский путь через /api, маппит ответ; !ok → []; исключение → []", async () => {
    const data = [order({ id: 2 })];
    const fn = stubFetch(data);
    expect(await fetchOrders()).toEqual(data);
    expect(fn).toHaveBeenCalledWith("/api/production/orders", { cache: "no-store" });

    stubFetch(null, false);
    expect(await fetchOrders()).toEqual([]);

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await fetchOrders()).toEqual([]);
  });

  it("createOrder: POST с JSON-телом входа; !ok → null; исключение → null", async () => {
    const created = order({ id: 11, product: "Шкаф ШРС" });
    const fn = stubFetch(created);
    const input = { product: "Шкаф ШРС", qty: 2, priority: "Высокий" };
    const result = await createOrder(input);
    expect(fn).toHaveBeenCalledWith("/api/production/orders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    expect(result).toEqual(created);

    stubFetch(null, false);
    expect(await createOrder(input)).toBeNull();

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await createOrder(input)).toBeNull();
  });

  it("updateOrderStage: PATCH по id с телом {stage}, возвращает res.ok; исключение → false", async () => {
    const fn = stubFetch(null, true);
    expect(await updateOrderStage(5, "assembly")).toBe(true);
    expect(fn).toHaveBeenCalledWith("/api/production/orders/5", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage: "assembly" }),
    });

    stubFetch(null, false);
    expect(await updateOrderStage(5, "assembly")).toBe(false);

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await updateOrderStage(5, "assembly")).toBe(false);
  });
});
