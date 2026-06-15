import { describe, expect, it } from "vitest";
import { formatDate, versionStatus } from "./spravochniki-rates";

const TODAY = "2026-06-15";

describe("versionStatus", () => {
  it("current: null end_date and past start", () => {
    expect(versionStatus({ start_date: "2026-06-10", end_date: null }, TODAY)).toBe("current");
  });

  it("current: start == today with null end", () => {
    expect(versionStatus({ start_date: TODAY, end_date: null }, TODAY)).toBe("current");
  });

  it("current: future end_date means still active", () => {
    expect(versionStatus({ start_date: "2026-06-01", end_date: "2026-07-01" }, TODAY)).toBe("current");
  });

  it("planned: future start_date with null end", () => {
    expect(versionStatus({ start_date: "2026-07-01", end_date: null }, TODAY)).toBe("planned");
  });

  it("planned: future start beats end_date check", () => {
    expect(versionStatus({ start_date: "2026-07-01", end_date: "2026-08-01" }, TODAY)).toBe("planned");
  });

  it("archived: closed in the past", () => {
    expect(versionStatus({ start_date: "2026-01-01", end_date: "2026-05-01" }, TODAY)).toBe("archived");
  });

  it("archived: end_date == today (half-open: today not included)", () => {
    expect(versionStatus({ start_date: "2026-01-01", end_date: TODAY }, TODAY)).toBe("archived");
  });
});

describe("formatDate", () => {
  it("formats YYYY-MM-DD to DD.MM.YYYY", () => {
    expect(formatDate("2026-06-10")).toBe("10.06.2026");
  });

  it("pads single-digit day and month", () => {
    expect(formatDate("2026-01-05")).toBe("05.01.2026");
  });

  it("null → dash", () => {
    expect(formatDate(null)).toBe("—");
  });
});
