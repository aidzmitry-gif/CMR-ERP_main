import { describe, expect, it } from "vitest";

import type { NomenclatureGroup } from "@/lib/reference-data";
import {
  buildBreadcrumb,
  filterFlatGroups,
  getDescendantIds,
  getNodeDepth,
} from "@/lib/spravochniki-categories";

const groups: NomenclatureGroup[] = [
  { id: 1, code: "ROOT", name: "Электроника", parent_id: null, is_active: true },
  { id: 2, code: "CHIPS", name: "Микросхемы", parent_id: 1, is_active: true },
  { id: 3, code: "RESIST", name: "Резисторы", parent_id: 1, is_active: true },
  { id: 4, code: "MCU", name: "Микроконтроллеры", parent_id: 2, is_active: true },
];

describe("getNodeDepth", () => {
  it("корень — глубина 1", () => expect(getNodeDepth(1, groups)).toBe(1));
  it("дочерний — глубина 2", () => expect(getNodeDepth(2, groups)).toBe(2));
  it("внук — глубина 3", () => expect(getNodeDepth(4, groups)).toBe(3));
  it("несуществующий id — 1 (не найден родитель)", () => expect(getNodeDepth(99, groups)).toBe(1));
});

describe("buildBreadcrumb", () => {
  it("корень: один элемент", () => expect(buildBreadcrumb(1, groups)).toEqual(["Электроника"]));
  it("дочерний: путь от корня", () =>
    expect(buildBreadcrumb(2, groups)).toEqual(["Электроника", "Микросхемы"]));
  it("внук: полный путь", () =>
    expect(buildBreadcrumb(4, groups)).toEqual([
      "Электроника",
      "Микросхемы",
      "Микроконтроллеры",
    ]));
});

describe("getDescendantIds", () => {
  it("корень — все потомки", () => {
    const ids = getDescendantIds(1, groups);
    expect(ids.has(2)).toBe(true);
    expect(ids.has(3)).toBe(true);
    expect(ids.has(4)).toBe(true);
    expect(ids.has(1)).toBe(false);
  });
  it("средний узел — только его потомки", () => {
    const ids = getDescendantIds(2, groups);
    expect(ids.has(4)).toBe(true);
    expect(ids.has(3)).toBe(false);
  });
  it("лист — пустое множество", () => expect(getDescendantIds(4, groups).size).toBe(0));
});

describe("filterFlatGroups", () => {
  it("пустой запрос — возвращает всё", () =>
    expect(filterFlatGroups(groups, "")).toHaveLength(groups.length));
  it("совпадение по имени", () => {
    const result = filterFlatGroups(groups, "микро");
    // Микросхемы (id=2) и Микроконтроллеры (id=4) совпадают, плюс предок Электроника (id=1)
    const ids = result.map((g) => g.id);
    expect(ids).toContain(1);
    expect(ids).toContain(2);
    expect(ids).toContain(4);
    expect(ids).not.toContain(3);
  });
  it("совпадение по коду", () => {
    const result = filterFlatGroups(groups, "MCU");
    const ids = result.map((g) => g.id);
    expect(ids).toContain(4); // MCU
    expect(ids).toContain(1); // предок
    expect(ids).toContain(2); // предок
  });
  it("нет совпадений — пустой массив", () =>
    expect(filterFlatGroups(groups, "zzznomatch")).toHaveLength(0));
});
