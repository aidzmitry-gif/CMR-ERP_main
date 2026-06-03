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
  it("разделяет активные и закрытые стадии и считает конверсию", () => {
    const f = computeFunnel([stage("new", 3, 300), stage("qual", 1, 200), stage("won", 1, 100)]);
    expect(f.activeCount).toBe(4);
    expect(f.activeSum).toBe(500);
    expect(f.wonCount).toBe(1);
    expect(f.wonSum).toBe(100);
    expect(f.conversion).toBeCloseTo((1 / 5) * 100);
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
