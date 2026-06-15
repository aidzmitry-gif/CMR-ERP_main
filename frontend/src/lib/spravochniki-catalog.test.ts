import { describe, expect, it } from "vitest";

import type { ReferenceCatalog, ReferenceMeta } from "@/lib/reference-data";
import { defaultRef, rowsSource, sortedDepartments } from "./spravochniki-catalog";

function makeRef(key: string, title: string): ReferenceMeta {
  return {
    key,
    title,
    module: "core",
    endpoint: `/system/refs/${key}`,
    owner_schema: "public",
    columns: [],
    permissions: [],
    archivable: true,
    versioned: false,
    ai_exposed: false,
    description: "",
  };
}

const mockCatalog: ReferenceCatalog = {
  departments: {
    Продажи: [makeRef("stages", "Стадии воронки")],
    Система: [makeRef("units", "Единицы измерения"), makeRef("currencies", "Валюты")],
    Закупки: [],
    Неизвестный: [makeRef("x", "Икс")],
  },
};

describe("sortedDepartments", () => {
  it("places Система before Продажи (canonical order)", () => {
    const groups = sortedDepartments(mockCatalog);
    const names = groups.map((g) => g.dept);
    expect(names.indexOf("Система")).toBeLessThan(names.indexOf("Продажи"));
  });

  it("places Продажи before Закупки", () => {
    const groups = sortedDepartments(mockCatalog);
    const names = groups.map((g) => g.dept);
    expect(names.indexOf("Продажи")).toBeLessThan(names.indexOf("Закупки"));
  });

  it("appends unknown departments after all known ones", () => {
    const groups = sortedDepartments(mockCatalog);
    const names = groups.map((g) => g.dept);
    expect(names.at(-1)).toBe("Неизвестный");
  });

  it("attaches correct icon for known depts", () => {
    const groups = sortedDepartments(mockCatalog);
    expect(groups.find((g) => g.dept === "Система")?.icon).toBe("⚙️");
    expect(groups.find((g) => g.dept === "Продажи")?.icon).toBe("📈");
  });

  it("attaches fallback icon for unknown dept", () => {
    const groups = sortedDepartments(mockCatalog);
    expect(groups.find((g) => g.dept === "Неизвестный")?.icon).toBe("📋");
  });

  it("preserves refs inside each department", () => {
    const groups = sortedDepartments(mockCatalog);
    const sys = groups.find((g) => g.dept === "Система");
    expect(sys?.refs).toHaveLength(2);
    expect(sys?.refs[0].key).toBe("units");
  });
});

describe("defaultRef", () => {
  it("returns the first ref of the first sorted dept (Система→units)", () => {
    const ref = defaultRef(mockCatalog);
    expect(ref?.key).toBe("units");
  });

  it("returns null for an empty catalog", () => {
    expect(defaultRef({ departments: {} })).toBeNull();
  });

  it("returns null when only dept has no refs", () => {
    expect(defaultRef({ departments: { Закупки: [] } })).toBeNull();
  });
});

describe("rowsSource", () => {
  it("CRUD: /system/refs/… → читается GET-ом по endpoint", () => {
    expect(rowsSource({ endpoint: "/system/refs/units", key: "core.units" })).toBe("crud");
    expect(rowsSource({ endpoint: "/system/refs/currency-rates", key: "core.currency_rates" })).toBe("crud");
    expect(rowsSource({ endpoint: "/system/refs/nomenclature-groups", key: "core.nomenclature_groups" })).toBe("crud");
  });

  it("query-list: номенклатура отдаётся reference.query списком", () => {
    expect(rowsSource({ endpoint: "/refs/skus", key: "core.skus" })).toBe("query-list");
  });

  it("lookup-only: контрагенты/контакты/сотрудники списком не выгружаются", () => {
    expect(rowsSource({ endpoint: "/refs/counterparties", key: "core.counterparties" })).toBe("lookup-only");
    expect(rowsSource({ endpoint: "/refs/contacts", key: "core.contacts" })).toBe("lookup-only");
    expect(rowsSource({ endpoint: "/refs/employees", key: "core.employees" })).toBe("lookup-only");
  });
});
