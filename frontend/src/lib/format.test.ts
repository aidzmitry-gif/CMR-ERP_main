import { describe, expect, it } from "vitest";

import { formatMoney, formatNumber } from "@/lib/format";

describe("format", () => {
  it("formatMoney добавляет символ ₽", () => {
    expect(formatMoney(1250000)).toMatch(/₽$/);
    expect(formatMoney(0)).toMatch(/0\s?₽/);
  });

  it("formatNumber форматирует без валюты", () => {
    const out = formatNumber(1000);
    expect(out).not.toContain("₽");
    expect(out.replace(/ |\s/g, "")).toBe("1000");
  });
});
