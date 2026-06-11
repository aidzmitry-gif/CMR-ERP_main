import { describe, expect, it } from "vitest";

import {
  contributionShare,
  formatByn,
  formatNh,
  type PayrollRow,
  totalContribution,
} from "@/lib/production-vyrabotka";

function row(over: Partial<PayrollRow>): PayrollRow {
  return {
    id: 1,
    name: "Сборщик",
    nh_output: 0,
    base: 0,
    premium: 0,
    total: 0,
    contribution: 0,
    ...over,
  };
}

// ru-RU группирует тысячи неразрывным пробелом (U+00A0); \s в JS-regex его матчит.
const stripWs = (s: string) => s.replace(/\s/g, "");

describe("production-vyrabotka", () => {
  it("formatByn: русский формат с суффиксом BYN", () => {
    expect(formatByn(910)).toBe("910 BYN");
    expect(formatByn(910.5)).toBe("910,5 BYN");
    expect(formatByn(0)).toBe("0 BYN");
    expect(stripWs(formatByn(1067.5))).toBe("1067,5BYN");
  });

  it("formatNh реэкспортирован из norms", () => {
    expect(formatNh(7.5)).toBe("7,5");
    expect(formatNh(0)).toBe("—");
  });

  it("totalContribution: сумма вкладов", () => {
    const rows = [row({ contribution: 1000 }), row({ contribution: 472.5 })];
    expect(totalContribution(rows)).toBe(1472.5);
  });

  it("contributionShare: доля вклада в процентах", () => {
    expect(contributionShare(row({ contribution: 750 }), 1000)).toBe(75);
    expect(contributionShare(row({ contribution: 250 }), 1000)).toBe(25);
  });

  it("contributionShare: ноль при пустом итоге", () => {
    expect(contributionShare(row({ contribution: 100 }), 0)).toBe(0);
  });
});
