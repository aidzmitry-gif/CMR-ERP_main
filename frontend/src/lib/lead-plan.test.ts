import { describe, expect, it } from "vitest";
import { planPace, workdayElapsedFraction, WORKDAY_END_HOUR, WORKDAY_START_HOUR } from "./lead-plan";

function at(hour: number, minute = 0): Date {
  const d = new Date(2026, 6, 11, hour, minute, 0);
  return d;
}

describe("workdayElapsedFraction", () => {
  it("0 до начала дня, 1 после конца", () => {
    expect(workdayElapsedFraction(at(WORKDAY_START_HOUR - 1))).toBe(0);
    expect(workdayElapsedFraction(at(WORKDAY_END_HOUR + 1))).toBe(1);
    expect(workdayElapsedFraction(at(WORKDAY_START_HOUR))).toBe(0);
    expect(workdayElapsedFraction(at(WORKDAY_END_HOUR))).toBe(1);
  });

  it("середина дня ≈ 0.5", () => {
    const midHour = Math.floor((WORKDAY_START_HOUR + WORKDAY_END_HOUR) / 2);
    const midMin = ((WORKDAY_START_HOUR + WORKDAY_END_HOUR) / 2 - midHour) * 60;
    expect(workdayElapsedFraction(at(midHour, midMin))).toBeCloseTo(0.5, 5);
  });
});

describe("planPace", () => {
  it("прогресс и остаток до нормы", () => {
    const p = planPace(6, 20, 0.5);
    expect(p.pct).toBe(30);
    expect(p.remaining).toBe(14);
    expect(p.expectedByNow).toBe(10); // 20 * 0.5
    expect(p.onTrack).toBe(false); // 6 < 10
  });

  it("успевает к темпу", () => {
    const p = planPace(12, 20, 0.5);
    expect(p.onTrack).toBe(true); // 12 >= 10
    expect(p.remaining).toBe(8);
  });

  it("перевыполнение зажато в 100% и остаток 0", () => {
    const p = planPace(25, 20, 1);
    expect(p.pct).toBe(100);
    expect(p.remaining).toBe(0);
    expect(p.onTrack).toBe(true);
  });

  it("нулевая цель = выполнено", () => {
    const p = planPace(0, 0, 0.5);
    expect(p.pct).toBe(100);
    expect(p.onTrack).toBe(true);
  });
});
