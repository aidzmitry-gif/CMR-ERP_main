import { describe, expect, it } from "vitest";
import { ageOn } from "./employee-profile";

describe("ageOn", () => {
  it("changes on the birthday, including a leap-day birthday", () => {
    expect(ageOn("2015-09-08", new Date(2026, 8, 7))).toBe(10);
    expect(ageOn("2015-09-08", new Date(2026, 8, 8))).toBe(11);
    expect(ageOn("2020-02-29", new Date(2025, 1, 28))).toBe(4);
    expect(ageOn("2020-02-29", new Date(2025, 2, 1))).toBe(5);
  });
  it("does not invent ages for missing, invalid or future dates", () => {
    expect(ageOn("")).toBeNull();
    expect(ageOn("2025-02-30")).toBeNull();
    expect(ageOn("2999-01-01")).toBeNull();
  });
});
