import { describe, expect, it } from "vitest";

import {
  type Claim,
  claimCounts,
  claimStatusLabel,
  claimStatusTone,
  sourceLabel,
} from "@/lib/procurement-claims";

function claim(over: Partial<Claim> = {}): Claim {
  return {
    id: 1,
    supplier: "",
    item: "АКБ 48V 100Ah",
    reason: "Непропай БМС",
    order_code: "№250",
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
});
