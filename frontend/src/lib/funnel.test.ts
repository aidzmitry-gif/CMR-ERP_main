import { describe, expect, it } from "vitest";

import { computeFunnel } from "@/lib/funnel";
import type { Stage } from "@/lib/types";

const stage = (id: string, count: number, sum: number): Stage => ({
  id,
  title: id,
  color: "#000",
  count,
  sum,
  deals: [],
});

describe("computeFunnel", () => {
  it("разделяет активные и закрытые стадии и считает конверсию (win rate)", () => {
    const f = computeFunnel([stage("new", 3, 300), stage("qual", 1, 200), stage("won", 1, 100)]);
    expect(f.activeCount).toBe(4);
    expect(f.activeSum).toBe(500);
    expect(f.wonCount).toBe(1);
    expect(f.wonSum).toBe(100);
    expect(f.lostCount).toBe(0);
    expect(f.conversion).toBeCloseTo(100); // win rate = won/(won+lost) = 1/1
  });

  it("исключает lost из «в работе» и считает win rate won/(won+lost)", () => {
    const f = computeFunnel([
      stage("new", 2, 200),
      stage("won", 3, 300),
      stage("lost", 1, 100),
    ]);
    expect(f.activeCount).toBe(2); // lost НЕ в работе
    expect(f.activeSum).toBe(200);
    expect(f.lostCount).toBe(1);
    expect(f.lostSum).toBe(100);
    expect(f.conversion).toBeCloseTo((3 / 4) * 100); // 75% = 3 won / (3 won + 1 lost)
  });

  it("конверсия 0 при пустой воронке", () => {
    expect(computeFunnel([]).conversion).toBe(0);
  });

  it("учитывает кастомный id «закрытой» стадии", () => {
    const f = computeFunnel([stage("a", 2, 20), stage("done", 2, 50)], "done");
    expect(f.wonCount).toBe(2);
    expect(f.wonSum).toBe(50);
  });
});
