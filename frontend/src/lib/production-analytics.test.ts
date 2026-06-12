import { describe, expect, it } from "vitest";

import { fmtByn, fmtNh, fmtPct, kpiTone } from "@/lib/production-analytics";

describe("production-analytics", () => {
  describe("fmtNh", () => {
    it("0 → '0,0'", () => expect(fmtNh(0)).toBe("0,0"));
    it("1 → '1,0'", () => expect(fmtNh(1)).toBe("1,0"));
    it("176.5 → '176,5'", () => expect(fmtNh(176.5)).toBe("176,5"));
  });

  describe("fmtPct", () => {
    it("95.5 → '95,5%'", () => expect(fmtPct(95.5)).toBe("95,5%"));
    it("100 → '100,0%'", () => expect(fmtPct(100)).toBe("100,0%"));
    it("0 → '0,0%'", () => expect(fmtPct(0)).toBe("0,0%"));
  });

  describe("fmtByn", () => {
    it("форматирует 2 знака после запятой", () => {
      expect(fmtByn(1234.567)).toContain(",57");
    });
    it("включает 'р.'", () => {
      expect(fmtByn(100)).toContain("р.");
    });
    it("0 → '0,00 р.'", () => expect(fmtByn(0)).toBe("0,00 р."));
  });

  describe("kpiTone — high (чем больше тем лучше)", () => {
    it("≥80 → green", () => {
      expect(kpiTone("high", 80)).toBe("text-green-600");
      expect(kpiTone("high", 100)).toBe("text-green-600");
    });

    it("60..79 → amber", () => {
      expect(kpiTone("high", 60)).toBe("text-amber-600");
      expect(kpiTone("high", 79)).toBe("text-amber-600");
    });

    it("<60 → red", () => {
      expect(kpiTone("high", 59)).toBe("text-red-600");
      expect(kpiTone("high", 0)).toBe("text-red-600");
    });
  });

  describe("kpiTone — low (чем меньше тем лучше)", () => {
    it("≤5 → green", () => {
      expect(kpiTone("low", 0)).toBe("text-green-600");
      expect(kpiTone("low", 5)).toBe("text-green-600");
    });

    it("6..15 → amber", () => {
      expect(kpiTone("low", 6)).toBe("text-amber-600");
      expect(kpiTone("low", 15)).toBe("text-amber-600");
    });

    it(">15 → red", () => {
      expect(kpiTone("low", 16)).toBe("text-red-600");
      expect(kpiTone("low", 100)).toBe("text-red-600");
    });
  });
});
