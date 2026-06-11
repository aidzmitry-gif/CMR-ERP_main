import { describe, expect, it } from "vitest";

import { type Bom } from "@/lib/production-bom";
import { type Norm } from "@/lib/production-norms";
import {
  coverageForProduct,
  nhTotal,
  normForProduct,
  type Order,
  stageLabel,
  zayavkiCounts,
} from "@/lib/production-zayavki";

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
});
