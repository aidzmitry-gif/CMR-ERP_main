import { describe, expect, it } from "vitest";

import {
  emptySupplier,
  filterSuppliers,
  statusLabel,
  type Supplier,
} from "@/lib/procurement-suppliers";

const S = (over: Partial<Supplier>): Supplier => ({
  id: 1,
  name: "Шэньчжэнь",
  unp: "ICN-1",
  country: "Китай",
  flag: "🇨🇳",
  contact_person: "",
  phone: "",
  email: "",
  payment_terms: "",
  lead_time_days: null,
  incoterms: "",
  status: "active",
  notes: "",
  ...over,
});

describe("statusLabel", () => {
  it("переводит статусы", () => {
    expect(statusLabel("active")).toBe("Активен");
    expect(statusLabel("blocked")).toBe("Заблокирован");
    expect(statusLabel("xxx")).toBe("xxx");
  });
});

describe("filterSuppliers", () => {
  const rows = [
    S({ id: 1, name: "Шэньчжэнь Бэттери", unp: "ICN-1", country: "Китай" }),
    S({ id: 2, name: "Минск Логистик", unp: "BY-9", country: "Беларусь" }),
  ];
  it("ищет по имени/УНП/стране, регистронезависимо", () => {
    expect(filterSuppliers(rows, "бэттери").map((s) => s.id)).toEqual([1]);
    expect(filterSuppliers(rows, "BY-9").map((s) => s.id)).toEqual([2]);
    expect(filterSuppliers(rows, "беларусь").map((s) => s.id)).toEqual([2]);
  });
  it("пустой запрос — все", () => {
    expect(filterSuppliers(rows, "  ")).toHaveLength(2);
  });
});

describe("emptySupplier", () => {
  it("даёт валидный пустой профиль (active, lead_time null)", () => {
    const e = emptySupplier();
    expect(e.status).toBe("active");
    expect(e.lead_time_days).toBeNull();
    expect(e.name).toBe("");
  });
});
