import { describe, expect, it } from "vitest";

import { moveDealToStage, recomputeStages } from "@/lib/board";
import type { Deal, Stage } from "@/lib/types";

const deal = (id: string, amount: number): Deal => ({
  id,
  number: `N-${id}`,
  company: "ООО",
  description: "d",
  amount,
  priority: "Средний",
  owner: "o",
});
const stage = (id: string, deals: Deal[]): Stage => ({ id, title: id, color: "#000", count: deals.length, sum: 0, deals });

describe("recomputeStages", () => {
  it("пересчитывает count и sum по сделкам стадии", () => {
    const [s] = recomputeStages([stage("new", [deal("1", 100), deal("2", 50)])]);
    expect(s.count).toBe(2);
    expect(s.sum).toBe(150);
  });
});

describe("moveDealToStage", () => {
  const stages = [stage("new", [deal("1", 100)]), stage("won", [])];

  it("перемещает сделку в целевую стадию и пересчитывает агрегаты", () => {
    const next = moveDealToStage(stages, "1", "won");
    expect(next.find((s) => s.id === "new")!.deals).toHaveLength(0);
    const won = next.find((s) => s.id === "won")!;
    expect(won.deals).toHaveLength(1);
    expect(won.count).toBe(1);
    expect(won.sum).toBe(100);
  });

  it("возвращает прежний массив, если сделка уже в целевой стадии", () => {
    expect(moveDealToStage(stages, "1", "new")).toBe(stages);
  });

  it("возвращает прежний массив для несуществующей сделки", () => {
    expect(moveDealToStage(stages, "999", "won")).toBe(stages);
  });
});
