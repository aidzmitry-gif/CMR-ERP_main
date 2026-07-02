import { describe, expect, it } from "vitest";

import {
  type Claim,
  claimCounts,
  claimStatusLabel,
  claimStatusTone,
  claimTypeLabel,
  filterClaims,
  sourceLabel,
} from "@/lib/procurement-claims";

function claim(over: Partial<Claim> = {}): Claim {
  return {
    id: 1,
    supplier: "",
    supplier_id: null,
    item: "АКБ 48V 100Ah",
    reason: "Непропай БМС",
    order_code: "№250",
    claim_type: "брак",
    qty_affected: 0,
    amount_byn: null,
    resolution: "",
    status: "open",
    source: "production",
    entity_ref: "production:qc:1",
    ...over,
  };
}

describe("procurement-claims", () => {
  it("claimStatusLabel: подписи статусов", () => {
    expect(claimStatusLabel("open")).toBe("Открыта");
    expect(claimStatusLabel("resolved")).toBe("Решена");
    expect(claimStatusLabel("rejected")).toBe("Отклонена");
  });

  it("claimStatusTone: тон по статусу", () => {
    expect(claimStatusTone("open")).toContain("amber");
    expect(claimStatusTone("resolved")).toContain("green");
    expect(claimStatusTone("rejected")).toContain("slate");
  });

  it("sourceLabel: источник претензии", () => {
    expect(sourceLabel("production")).toBe("Брак производства");
    expect(sourceLabel("manual")).toBe("manual");
    expect(sourceLabel("")).toBe("—");
  });

  it("claimCounts: всего/открыто/решено/без поставщика", () => {
    const claims = [
      claim({ id: 1, status: "open", supplier: "" }), // открыта, без поставщика
      claim({ id: 2, status: "open", supplier: "ООО Поставщик" }), // открыта, с поставщиком
      claim({ id: 3, status: "resolved", supplier: "ООО Поставщик" }),
    ];
    expect(claimCounts(claims)).toEqual({
      total: 3,
      open: 2,
      resolved: 1,
      withoutSupplier: 1,
    });
    expect(claimCounts([])).toEqual({ total: 0, open: 0, resolved: 0, withoutSupplier: 0 });
  });

  it("claimTypeLabel: тип или прочерк", () => {
    expect(claimTypeLabel("недопоставка")).toBe("недопоставка");
    expect(claimTypeLabel("")).toBe("—");
  });

  it("filterClaims: по статусу/типу/строке", () => {
    const claims = [
      claim({ id: 1, status: "open", claim_type: "брак", item: "АКБ" }),
      claim({ id: 2, status: "resolved", claim_type: "недопоставка", item: "Зарядка" }),
      claim({ id: 3, status: "open", claim_type: "недопоставка", item: "АКБ доп" }),
    ];
    expect(filterClaims(claims, { status: "open" }).map((c) => c.id)).toEqual([1, 3]);
    expect(filterClaims(claims, { type: "недопоставка" }).map((c) => c.id)).toEqual([2, 3]);
    expect(filterClaims(claims, { query: "акб" }).map((c) => c.id)).toEqual([1, 3]);
    expect(filterClaims(claims, { status: "open", type: "недопоставка" }).map((c) => c.id)).toEqual([3]);
    expect(filterClaims(claims, {})).toHaveLength(3);
  });
});
