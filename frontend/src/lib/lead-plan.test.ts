import { describe, expect, it } from "vitest";
import {
  planPace,
  workdayElapsedFraction,
  WORKDAY_END_HOUR,
  WORKDAY_START_HOUR,
  workingMinutesBetween,
} from "./lead-plan";

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

describe("workingMinutesBetween", () => {
  // Цикл 14 — честный SLA: ночь (вне окна 9-18) не считается ожиданием.
  const d = (day: number, hour: number, minute = 0) => new Date(2026, 6, day, hour, minute, 0);

  it("внутри рабочего дня — обычная разница", () => {
    expect(workingMinutesBetween(d(10, 10, 0), d(10, 11, 30))).toBe(90);
  });

  it("ночной лид: 23:00 → 9:10 = 10 рабочих минут, а не 10 часов", () => {
    expect(workingMinutesBetween(d(10, 23, 0), d(11, 9, 10))).toBe(10);
  });

  it("до начала дня клэмпится к 9:00", () => {
    expect(workingMinutesBetween(d(10, 7, 0), d(10, 9, 30))).toBe(30);
  });

  it("вне окна (вечер) — ноль", () => {
    expect(workingMinutesBetween(d(10, 19, 0), d(10, 20, 0))).toBe(0);
  });

  it("несколько дней: хвост + полный день + утро", () => {
    // 10-го 17:00→18:00 (60) + весь 11-й день (540) + 12-го 9:00→10:00 (60)
    expect(workingMinutesBetween(d(10, 17, 0), d(12, 10, 0))).toBe(660);
  });

  it("будущее/равное время — ноль", () => {
    expect(workingMinutesBetween(d(10, 12, 0), d(10, 12, 0))).toBe(0);
    expect(workingMinutesBetween(d(10, 12, 0), d(10, 11, 0))).toBe(0);
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
