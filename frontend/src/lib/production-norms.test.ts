import { describe, expect, it } from "vitest";

import {
  filterByKind,
  formatNh,
  type Norm,
  normCounts,
  normKindLabel,
  normStatusLabel,
} from "@/lib/production-norms";

function norm(over: Partial<Norm>): Norm {
  return { id: 1, kind: "product", title: "Изделие", nh: 0, status: "none", note: "", ...over };
}

describe("production-norms", () => {
  it("formatNh: русский формат, целое без дробной, ноль → тире", () => {
    expect(formatNh(10)).toBe("10");
    expect(formatNh(7.5)).toBe("7,5");
    expect(formatNh(0)).toBe("—");
    expect(formatNh(0.5)).toBe("0,5");
    expect(formatNh(40)).toBe("40");
  });

  it("normStatusLabel: подписи статусов", () => {
    expect(normStatusLabel("none")).toBe("Нет нормы");
    expect(normStatusLabel("pending")).toBe("На утверждении");
    expect(normStatusLabel("approved")).toBe("Утверждена");
  });

  it("normKindLabel: подписи видов", () => {
    expect(normKindLabel("product")).toBe("Изделие");
    expect(normKindLabel("operation")).toBe("Операция");
  });

  it("filterByKind: отбор по виду", () => {
    const norms = [
      norm({ id: 1, kind: "product" }),
      norm({ id: 2, kind: "operation" }),
      norm({ id: 3, kind: "product" }),
    ];
    expect(filterByKind(norms, "product").map((n) => n.id)).toEqual([1, 3]);
    expect(filterByKind(norms, "operation").map((n) => n.id)).toEqual([2]);
  });

  it("normCounts: счётчики для KPI", () => {
    const norms = [
      norm({ id: 1, status: "approved" }),
      norm({ id: 2, status: "pending" }),
      norm({ id: 3, status: "pending" }),
      norm({ id: 4, status: "none" }),
    ];
    expect(normCounts(norms)).toEqual({ total: 4, pending: 2, none: 1, approved: 1 });
  });

  it("normCounts: пустой справочник", () => {
    expect(normCounts([])).toEqual({ total: 0, pending: 0, none: 0, approved: 0 });
  });
});
