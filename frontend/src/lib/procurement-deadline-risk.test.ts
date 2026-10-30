import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { fetchCustomerDeadlines, type CustomerDeadlines } from "./procurement-machine";

export function deadlineReview(): CustomerDeadlines {
  return { organization_id: 1, order_id: 7, status: "live_review", source: "outstanding_expected_reservations",
    earliest_required_arrival: "2026-12-28", unresolved_deadlines: 0, complete_customer_demand: false, at_risk: true,
    items: [{ reservation_id: 4, deal_id: 3, sku_code: "A", outstanding_qty: "60.00",
      ship_deadline: "2026-12-31", required_arrival: "2026-12-28", deadline_status: "dated", at_risk: true }],
    risk_details: { version: 1, required_by: "2026-12-31", target_arrival_date: "2027-01-01", slack_days: -4,
      schedule_start_date: "2026-10-10", schedule_start_in_past: false,
      items: [{ reservation_id: 4, number: "DEAL-EXPECTED", counterparty: "Synthetic buyer", required_by: "2026-12-31",
        slack_days: -4, penalty_rate_pct: "1.00", penalty_cap_pct: "10.00", penalty_terms: "Synthetic contract" }] } };
}

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => { fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => vi.unstubAllGlobals());
const response = (v: unknown) => ({ ok: true, status: 200, json: async () => v });

it("reads current linked terms in the exact organization without issuing commands", async () => {
  const value = deadlineReview(); fetchMock.mockResolvedValue(response(value));
  expect(await fetchCustomerDeadlines(1, 7)).toEqual(value);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock).toHaveBeenCalledWith("/api/procurement/organizations/1/orders/7/customer-deadlines", { cache: "no-store" });
});

it("accepts an existing server response without inventing detailed terms", async () => {
  const value = deadlineReview(); delete value.risk_details;
  fetchMock.mockResolvedValue(response(value));
  expect((await fetchCustomerDeadlines(1, 7)).risk_details).toBeUndefined();
});

it.each(["version", "calendar", "percent", "reservation", "fractional_days", "schedule"])("rejects malformed risk details: %s", async kind => {
  const value = deadlineReview(); const d = value.risk_details!;
  if (kind === "version") (d as { version: number }).version = 2;
  if (kind === "calendar") d.required_by = "2026-02-30";
  if (kind === "percent") d.items[0].penalty_rate_pct = "NaN";
  if (kind === "reservation") d.items[0].reservation_id = 999;
  if (kind === "fractional_days") d.slack_days = -0.5;
  if (kind === "schedule") d.schedule_start_date = null;
  fetchMock.mockResolvedValue(response(value));
  await expect(fetchCustomerDeadlines(1, 7)).rejects.toThrow("Некорректный обзор клиентских сроков");
});
