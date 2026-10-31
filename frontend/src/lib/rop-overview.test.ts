import { describe, expect, it } from "vitest";
import { readRopDeals, ropSnapshot, ropStepTime, type RopDeal } from "./rop-overview";

const now = new Date("2026-10-31T21:00:00Z"); // 1 November, midnight in Minsk.
const deal = (id: number, patch: Partial<RopDeal> = {}): RopDeal => ({
  id, number: `D-${id}`, title: `Сделка ${id}`, counterparty: "Учебный клиент",
  stage: "new", owner: "Иван", owner_id: 7, next_step: "Позвонить",
  next_step_at: "2026-11-01T09:00:00", expected_close_date: "01.11.2026", probability: null,
  ...patch,
});

describe("ROP current snapshot", () => {
  it("reconciles stages and totals without treating unknown stages as open", () => {
    const result = ropSnapshot([
      deal(1), deal(2, { stage: "cond_lost" }), deal(3, { stage: "won" }),
      deal(4, { stage: "lost" }), deal(5, { stage: "legacy_stage" }), deal(6, { stage: "constructor" }),
    ], now);
    expect(result).toMatchObject({ total: 6, open: 2, won: 1, lost: 1, unknown: 2 });
    expect(result.stages.reduce((sum, row) => sum + row.count, 0)).toBe(6);
    expect(result.stages.find(row => row.id === "constructor")).toMatchObject({ count: 1, title: "Неизвестный этап: constructor" });
    expect(result.attention).toEqual([]);
  });

  it("separates same-name owners, combines one ID despite label changes, and preserves unassigned", () => {
    const result = ropSnapshot([
      deal(1), deal(2, { owner_id: 8 }), deal(3, { owner: "Иван Петров" }),
      deal(4, { owner_id: null }), deal(5, { owner_id: null, owner: "Другой текст" }),
    ], now);
    expect(result.team).toHaveLength(3);
    expect(result.team.find(row => row.ownerId === 7)).toMatchObject({ total: 2, open: 2, labels: new Set(["Иван", "Иван Петров"]) });
    expect(result.team.find(row => row.ownerId === 8)).toMatchObject({ total: 1 });
    expect(result.team.find(row => row.ownerId === null)).toMatchObject({ total: 2 });
    expect(result.team.reduce((sum, row) => sum + row.total, 0)).toBe(result.total);
  });

  it("uses UTC for naive steps and Minsk calendar for closing dates at midnight", () => {
    expect(ropStepTime("2026-11-01T00:00:00+03:00")).toBe(now.getTime());
    expect(ropStepTime("2026-10-31T21:00:00")).toBe(now.getTime());
    const result = ropSnapshot([
      deal(1, { next_step_at: "2026-10-31T20:59:59", expected_close_date: "31.10.2026" }),
      deal(2, { next_step_at: "2026-10-31T21:00:00Z" }),
      deal(3, { next_step_at: "2026-11-01T00:00:00+03:00" }),
    ], now);
    expect(result).toMatchObject({ overdue: 1, lateClose: 1 });
    expect(result.attention.map(row => row.deal.id)).toEqual([1]);
  });

  it("discloses invalid dates instead of inventing overdue dates and ignores closed deal reminders", () => {
    const result = ropSnapshot([
      deal(1, { next_step_at: "2026-02-31T09:00:00", expected_close_date: "31.02.2026" }),
      deal(2, { next_step_at: "2026-11-01T25:00:00", expected_close_date: "2026-10-01" }),
      deal(3, { stage: "won", next_step: null, next_step_at: null, expected_close_date: "31.10.2026" }),
      deal(4, { stage: "lost", next_step_at: "bad date" }),
    ], now);
    expect(result).toMatchObject({ invalidDate: 2, overdue: 0, lateClose: 0, missingStep: 0 });
    expect(result.attention.map(row => row.deal.id)).toEqual([1, 2]);
    expect(ropStepTime("2028-02-29T09:00:00.123456")).not.toBeNull();
  });

  it("counts each attention deal once, sorts overdue first, and keeps conditional refusals actionable", () => {
    const result = ropSnapshot([
      deal(1, { next_step: null, next_step_at: null }),
      deal(2, { stage: "cond_lost", next_step: " ", next_step_at: "2026-10-30T08:00:00", expected_close_date: "31.10.2026" }),
      deal(3, { next_step_at: "2026-10-31T08:00:00" }),
    ], now);
    expect(result).toMatchObject({ open: 3, overdue: 2, missingStep: 2, lateClose: 1 });
    expect(result.attention.map(row => row.deal.id)).toEqual([2, 3, 1]);
    expect(result.attention[0].reasons).toHaveLength(3);
    expect(result.team[0].attention).toBe(3);
  });

  it("does not infer absent probabilities or mutate source records", () => {
    const rows = [deal(1), deal(2, { probability: 0 }), deal(3, { probability: 65 }), deal(4, { stage: "won" })];
    const before = structuredClone(rows);
    expect(ropSnapshot(rows, now).withoutProbability).toBe(1);
    expect(rows).toEqual(before);
    expect(rows[0].probability).toBeNull();
  });

  it.each([
    ["object instead of array", {}],
    ["duplicate IDs", [deal(1), deal(1)]],
    ["missing canonical owner ID", [{ ...deal(1), owner_id: undefined }]],
    ["impossible probability", [deal(1, { probability: 101 })]],
    ["non-numeric ID", [{ ...deal(1), id: "1" }]],
  ])("rejects malformed native payload: %s", (_case, value) => {
    expect(() => readRopDeals(value)).toThrow();
    expect(readRopDeals([])).toEqual([]);
  });
});
