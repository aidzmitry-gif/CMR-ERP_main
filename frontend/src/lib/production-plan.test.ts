import { describe, expect, it } from "vitest";

import { fmtNh, loadTone } from "@/lib/production-plan";

describe("production-plan", () => {
  describe("loadTone", () => {
    it("≤69 → green", () => {
      expect(loadTone(0)).toContain("green");
      expect(loadTone(50)).toContain("green");
      expect(loadTone(69)).toContain("green");
    });

    it("70..100 → amber", () => {
      expect(loadTone(70)).toContain("amber");
      expect(loadTone(85)).toContain("amber");
      expect(loadTone(100)).toContain("amber");
    });

    it(">100 → red", () => {
      expect(loadTone(101)).toContain("red");
      expect(loadTone(150)).toContain("red");
    });
  });

  describe("fmtNh", () => {
    it("0 → '0,0'", () => {
      expect(fmtNh(0)).toBe("0,0");
    });

    it("1 → '1,0'", () => {
      expect(fmtNh(1)).toBe("1,0");
    });

    it("176.5 → '176,5'", () => {
      expect(fmtNh(176.5)).toBe("176,5");
    });

    it("0.25 → '0,3' (round)", () => {
      expect(fmtNh(0.25)).toBe("0,3");
    });

    it("704 → '704,0'", () => {
      expect(fmtNh(704)).toBe("704,0");
    });
  });
});
