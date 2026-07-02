import { describe, expect, it } from "vitest";

import {
  PROGRESSION_STAGES,
  SALES_STAGES,
  STAGE_BY_ID,
  TERMINAL_STAGES,
  progressionIndex,
} from "@/lib/sales-stages";

describe("SALES_STAGES (канон, зеркало backend stages.py)", () => {
  it("11 стадий, начинается с new, заканчивается lost", () => {
    expect(SALES_STAGES).toHaveLength(11);
    expect(SALES_STAGES[0].id).toBe("new");
    expect(SALES_STAGES.at(-1)!.id).toBe("lost");
  });

  it("STAGE_BY_ID отдаёт заголовок по id", () => {
    expect(STAGE_BY_ID.price_req.title).toBe("Цена запрошена");
    expect(STAGE_BY_ID.won.title).toBe("Успех");
  });

  it("TERMINAL_STAGES — won/lost, но НЕ cond_lost (реанимируемый)", () => {
    expect(TERMINAL_STAGES.has("won")).toBe(true);
    expect(TERMINAL_STAGES.has("lost")).toBe(true);
    expect(TERMINAL_STAGES.has("cond_lost")).toBe(false);
  });
});

describe("PROGRESSION_STAGES (линейный степпер)", () => {
  it("9 стадий: прогрессия без терминалов-отказа, заканчивается won", () => {
    expect(PROGRESSION_STAGES).toHaveLength(9);
    expect(PROGRESSION_STAGES.some((s) => s.id === "cond_lost")).toBe(false);
    expect(PROGRESSION_STAGES.some((s) => s.id === "lost")).toBe(false);
    expect(PROGRESSION_STAGES.at(-1)!.id).toBe("won");
  });
});

describe("progressionIndex", () => {
  it("индекс в прогрессии: new=0, won=8 (последняя)", () => {
    expect(progressionIndex("new")).toBe(0);
    expect(progressionIndex("won")).toBe(8);
  });

  it("−1 для терминалов-отказа и неизвестной стадии (степпер без активного узла)", () => {
    expect(progressionIndex("cond_lost")).toBe(-1);
    expect(progressionIndex("lost")).toBe(-1);
    expect(progressionIndex("какая-то")).toBe(-1);
  });
});
