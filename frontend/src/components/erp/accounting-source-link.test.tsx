import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { AccountingSourceLink } from "./accounting-source-link";
afterEach(cleanup);
const key = "b5b089ab-0000-4000-8000-000000000001";
it("routes an exact shipment source to its own book and never to procurement", () => {
  render(<AccountingSourceLink org="7" source={`wms:physical-shipment:7:${key}`} />);
  expect(screen.getByRole("link")).toHaveAttribute("href", `/api/accounting/organizations/7/shipments/${key}/document`);
  expect(screen.queryByText("Открыть первичные накладные")).not.toBeInTheDocument();
});
it.each([`wms:physical-shipment:8:${key}`, `wms:physical-shipment:7:${key}/extra`, "manual:unknown", "procurement:receipt:8x"])("does not fabricate a link for %s", source => {
  render(<AccountingSourceLink org="7" source={source} />);
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
});
