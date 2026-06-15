import { describe, expect, it } from "vitest";

import { clusterDuplicates, clusterSurvivor } from "./spravochniki-merge";

const M = [
  { id: 1045, name: "ООО «Старт»" },
  { id: 777, name: "ООО «Старт» (из 1С)" },
  { id: 388, name: "Старт (Bitrix)" },
];

describe("clusterSurvivor", () => {
  it("возвращает первого члена", () => {
    expect(clusterSurvivor({ unp: "191234567", members: M })).toEqual(M[0]);
  });
  it("возвращает undefined для пустого кластера", () => {
    expect(clusterSurvivor({ unp: "X", members: [] })).toBeUndefined();
  });
});

describe("clusterDuplicates", () => {
  it("возвращает всех кроме первого", () => {
    expect(clusterDuplicates({ unp: "191234567", members: M })).toEqual(M.slice(1));
  });
  it("возвращает пустой массив при одном члене", () => {
    expect(clusterDuplicates({ unp: "X", members: [M[0]] })).toEqual([]);
  });
  it("возвращает пустой массив при пустом кластере", () => {
    expect(clusterDuplicates({ unp: "X", members: [] })).toEqual([]);
  });
});
