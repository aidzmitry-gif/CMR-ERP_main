import { describe, expect, it } from "vitest";

import { formatSyncSummary } from "./spravochniki-import";

describe("formatSyncSummary", () => {
  it("maps all fields to display items in correct order", () => {
    const result = formatSyncSummary({
      counterparties: 218,
      new_counterparties: 140,
      counterparty_aliases: 14,
      stock: 0,
    });
    expect(result).toHaveLength(4);
    expect(result[0]).toEqual({ label: "Контрагентов обработано", value: 218 });
    expect(result[1]).toEqual({ label: "Создано новых", value: 140 });
    expect(result[2]).toEqual({ label: "Алиасов добавлено", value: 14 });
    expect(result[3]).toEqual({ label: "Позиций склада", value: 0 });
  });

  it("handles all-zero values", () => {
    const result = formatSyncSummary({
      counterparties: 0,
      new_counterparties: 0,
      counterparty_aliases: 0,
      stock: 0,
    });
    expect(result.every((item) => item.value === 0)).toBe(true);
  });

  it("preserves large numbers verbatim", () => {
    const result = formatSyncSummary({
      counterparties: 100_000,
      new_counterparties: 50_000,
      counterparty_aliases: 1_234,
      stock: 9_999,
    });
    expect(result[0].value).toBe(100_000);
    expect(result[3].value).toBe(9_999);
  });
});
