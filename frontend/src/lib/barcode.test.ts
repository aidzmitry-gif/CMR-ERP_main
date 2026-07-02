import { describe, expect, it } from "vitest";

import { code39Bars, isCode39 } from "@/lib/barcode";

describe("isCode39", () => {
  it("ASCII код ячейки кодируем", () => {
    expect(isCode39("A-01-02")).toBe(true);
    expect(isCode39("RECV01")).toBe(true);
  });
  it("кириллица и пусто — не кодируемо", () => {
    expect(isCode39("ПРМ-2026")).toBe(false);
    expect(isCode39("")).toBe(false);
  });
});

describe("code39Bars", () => {
  it("даёт непустой набор штрихов и положительную ширину для валидного кода", () => {
    const { bars, width } = code39Bars("A-01");
    expect(bars.length).toBeGreaterThan(0);
    expect(width).toBeGreaterThan(0);
    expect(bars.every((b) => b.w > 0)).toBe(true);
  });
  it("некодируемое значение → пусто", () => {
    expect(code39Bars("ПРМ").bars).toHaveLength(0);
  });
});
