import { describe, expect, it } from "vitest";

import { decisionLabel, formatPassRate, REWORK_REASONS } from "@/lib/production-otk";

describe("production-otk", () => {
  it("decisionLabel: подписи решений", () => {
    expect(decisionLabel("accept")).toBe("Принять");
    expect(decisionLabel("rework")).toBe("Доработка");
    expect(decisionLabel("scrap")).toBe("Брак");
  });

  it("formatPassRate: проценты с запятой", () => {
    expect(formatPassRate(96)).toBe("96%");
    expect(formatPassRate(95.5)).toBe("95,5%");
    expect(formatPassRate(0)).toBe("0%");
  });

  it("REWORK_REASONS: непустой преднабор причин", () => {
    expect(REWORK_REASONS.length).toBeGreaterThan(0);
    expect(REWORK_REASONS).toContain("Пайка БМС · непропай / перемычка");
  });
});
