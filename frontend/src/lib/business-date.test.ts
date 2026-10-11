import { expect, it } from "vitest";
import { businessDate } from "./business-date";

it.each([
  ["2026-07-31T20:59:59Z", "2026-07-31"],
  ["2026-07-31T21:00:00Z", "2026-08-01"],
  ["2026-12-31T21:00:00Z", "2027-01-01"],
])("uses the Minsk calendar at month/year boundaries: %s", (instant, expected) => {
  expect(businessDate(new Date(instant))).toBe(expected);
});
