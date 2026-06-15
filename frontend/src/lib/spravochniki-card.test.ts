import { describe, expect, it } from "vitest";

import type { CounterpartyAlias } from "./reference-data";
import { formatAuditDate, groupAliasesBySource } from "./spravochniki-card";

function alias(source: string, external_ref: string): CounterpartyAlias {
  return { source, external_ref, created_at: "2026-06-01T10:00:00Z" };
}

describe("groupAliasesBySource", () => {
  it("empty input returns empty object", () => {
    expect(groupAliasesBySource([])).toEqual({});
  });

  it("single alias is grouped under its source", () => {
    expect(groupAliasesBySource([alias("1C", "000231")])).toEqual({
      "1C": [{ source: "1C", external_ref: "000231", created_at: "2026-06-01T10:00:00Z" }],
    });
  });

  it("two aliases from same source stay together", () => {
    const result = groupAliasesBySource([alias("1C", "001"), alias("1C", "002")]);
    expect(result["1C"]).toHaveLength(2);
  });

  it("aliases from different sources are separated", () => {
    const result = groupAliasesBySource([alias("1C", "001"), alias("Bitrix24", "14502")]);
    expect(Object.keys(result).sort()).toEqual(["1C", "Bitrix24"]);
  });

  it("preserves insertion order of sources", () => {
    const result = groupAliasesBySource([alias("1C", "001"), alias("Bitrix24", "002")]);
    expect(Object.keys(result)).toEqual(["1C", "Bitrix24"]);
  });
});

describe("formatAuditDate", () => {
  it("formats ISO timestamp to DD.MM.YYYY", () => {
    expect(formatAuditDate("2026-06-05T12:34:56Z")).toBe("05.06.2026");
  });

  it("pads single-digit day and month", () => {
    expect(formatAuditDate("2026-01-09T00:00:00Z")).toBe("09.01.2026");
  });

  it("handles end-of-year date without TZ drift", () => {
    expect(formatAuditDate("2026-12-31T23:59:59Z")).toBe("31.12.2026");
  });
});
