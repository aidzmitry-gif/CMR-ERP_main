import { describe, expect, it } from "vitest";

import { FALLBACK_CATALOG, buildQueryInput } from "./spravochniki-ai";

describe("buildQueryInput", () => {
  it("passes ref and strips all empty optional fields", () => {
    const result = buildQueryInput({ ref: "core.vat_rates", key: "", as_of: "", name: "", limit: "" });
    expect(result).toEqual({ ref: "core.vat_rates" });
  });

  it("includes key when non-empty", () => {
    const result = buildQueryInput({ ref: "core.vat_rates", key: "НДС", as_of: "", name: "", limit: "" });
    expect(result).toEqual({ ref: "core.vat_rates", key: "НДС" });
  });

  it("includes as_of and limit together", () => {
    const result = buildQueryInput({ ref: "core.vat_rates", key: "НДС", as_of: "2026-05-15", name: "", limit: "10" });
    expect(result).toEqual({ ref: "core.vat_rates", key: "НДС", as_of: "2026-05-15", limit: 10 });
  });

  it("ignores limit=0", () => {
    const result = buildQueryInput({ ref: "core.counterparties", key: "", as_of: "", name: "", limit: "0" });
    expect(result).toEqual({ ref: "core.counterparties" });
  });

  it("ignores negative limit", () => {
    const result = buildQueryInput({ ref: "core.counterparties", key: "", as_of: "", name: "", limit: "-5" });
    expect(result).toEqual({ ref: "core.counterparties" });
  });

  it("includes name when non-empty", () => {
    const result = buildQueryInput({ ref: "core.counterparties", key: "", as_of: "", name: "Ромашка", limit: "" });
    expect(result).toEqual({ ref: "core.counterparties", name: "Ромашка" });
  });

  it("trims whitespace from string fields", () => {
    const result = buildQueryInput({ ref: "core.vat_rates", key: "  НДС  ", as_of: " 2026-01-01 ", name: "", limit: "" });
    expect(result).toEqual({ ref: "core.vat_rates", key: "НДС", as_of: "2026-01-01" });
  });
});

describe("FALLBACK_CATALOG", () => {
  it("has reference.query tool", () => {
    expect(FALLBACK_CATALOG.tool.name).toBe("reference.query");
  });

  it("tool has required params", () => {
    expect(FALLBACK_CATALOG.tool.params).toContain("ref");
    expect(FALLBACK_CATALOG.tool.params).toContain("as_of");
  });

  it("has at least 4 references", () => {
    expect(FALLBACK_CATALOG.references.length).toBeGreaterThanOrEqual(4);
  });

  it("all references have key, title, endpoint, description", () => {
    for (const ref of FALLBACK_CATALOG.references) {
      expect(ref.key).toBeTruthy();
      expect(ref.title).toBeTruthy();
      expect(ref.endpoint).toBeTruthy();
      expect(ref.description).toBeTruthy();
    }
  });

  it("versioned references have scd2.start_date semantic", () => {
    const versioned = FALLBACK_CATALOG.references.filter((r) => r.versioned);
    for (const ref of versioned) {
      const hasScd2 = ref.columns.some((c) => c.semantic.includes("scd2"));
      expect(hasScd2).toBe(true);
    }
  });
});
