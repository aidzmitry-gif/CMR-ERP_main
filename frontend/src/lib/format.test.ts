import { describe, expect, it } from "vitest";

import { formatMoney, formatNextStep, formatNumber } from "@/lib/format";

describe("format", () => {
  it("formatMoney adds ruble sign", () => {
    expect(formatMoney(1250000)).toMatch(/₽$/);
    expect(formatMoney(0)).toMatch(/0\s?₽/);
  });

  it("formatNumber formats without currency", () => {
    const out = formatNumber(1000);
    expect(out).not.toContain("₽");
    expect(out.replace(/ |\s/g, "")).toBe("1000");
  });
});

describe("formatNextStep", () => {
  it("returns dash for null", () => expect(formatNextStep(null)).toBe("—"));
  it("returns dash for undefined", () => expect(formatNextStep(undefined)).toBe("—"));
  it("returns dash for empty string", () => expect(formatNextStep("")).toBe("—"));
  it("formats ISO datetime to include time parts", () => {
    const result = formatNextStep("2026-07-15T14:30");
    expect(result).toContain("14");
    expect(result).toContain("30");
  });
  it("passes through non-ISO string unchanged", () => {
    expect(formatNextStep("non-iso text")).toBe("non-iso text");
  });
});
