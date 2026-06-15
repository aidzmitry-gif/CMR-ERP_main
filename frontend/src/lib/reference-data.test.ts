import { describe, expect, it } from "vitest";

import {
  flattenCatalog,
  isCurrentVersion,
  sortVersionsDesc,
  totalDuplicates,
  type ReferenceCatalog,
  type ReferenceMeta,
} from "./reference-data";

function meta(key: string): ReferenceMeta {
  return {
    key,
    title: key,
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

describe("flattenCatalog", () => {
  it("разворачивает отделы в плоский список с прикреплённым department", () => {
    const catalog: ReferenceCatalog = {
      departments: {
        Система: [meta("core.units"), meta("core.currencies")],
        Продажи: [meta("sales.stages")],
      },
    };
    const flat = flattenCatalog(catalog);
    expect(flat).toHaveLength(3);
    expect(flat.find((r) => r.key === "sales.stages")?.department).toBe("Продажи");
    expect(flat.filter((r) => r.department === "Система")).toHaveLength(2);
  });

  it("пустой каталог → пустой список", () => {
    expect(flattenCatalog({ departments: {} })).toEqual([]);
  });
});

describe("isCurrentVersion", () => {
  it("текущая — без даты окончания (end_date=null)", () => {
    expect(isCurrentVersion({ end_date: null })).toBe(true);
    expect(isCurrentVersion({ end_date: "2026-05-01" })).toBe(false);
  });
});

describe("sortVersionsDesc", () => {
  it("сортирует версии по убыванию start_date (новая — первой), не мутируя вход", () => {
    const rows = [
      { start_date: "2026-01-01", rate: 3.18 },
      { start_date: "2026-05-01", rate: 3.25 },
      { start_date: "2026-03-01", rate: 3.21 },
    ];
    const sorted = sortVersionsDesc(rows);
    expect(sorted.map((r) => r.start_date)).toEqual(["2026-05-01", "2026-03-01", "2026-01-01"]);
    expect(rows[0].start_date).toBe("2026-01-01"); // исходный массив не тронут
  });
});

describe("totalDuplicates", () => {
  it("считает кандидатов сверх эталона по всем кластерам", () => {
    const clusters = [
      { unp: "111", members: [{ id: 1, name: "A" }, { id: 2, name: "A дубль" }] },
      { unp: "222", members: [{ id: 3, name: "B" }, { id: 4, name: "B2" }, { id: 5, name: "B3" }] },
    ];
    expect(totalDuplicates(clusters)).toBe(3); // (2-1) + (3-1)
  });

  it("нет кластеров → 0", () => {
    expect(totalDuplicates([])).toBe(0);
  });
});
