import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchDashboard, fetchDashboardServer, type Dashboard } from "./wms-warehouse";

const data = (): Dashboard => ({
  organization_id: 7, report_date: "2026-07-01", period_start: "2026-07-01T00:00:00",
  period_end: "2026-07-02T00:00:00", period_basis: "stored_registration_date",
  receipts_pending_qc: 3, tasks_putaway_open: 1, tasks_pick_open: 2, inventories_open: 0,
  movement_rows_today_in: 5, movement_rows_today_out: 2, gateway: true,
  alerts_count: null, alerts_deficit_value: null, inventory_value: null,
  recon_max_diff_value: null, recon_total_diff_value: null,
  valuation_unavailable_reason: "organization_valuation_unavailable",
  movements_today_in: null, movements_today_out: null, quantity_unavailable_reason: "unit_snapshot_unavailable",
});
function stub(value: unknown, ok = true) {
  const fn = vi.fn().mockResolvedValue({ ok, json: async () => value });
  vi.stubGlobal("fetch", fn); return fn;
}
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("WMS dashboard reads", () => {
  it("SSR forwards trusted headers and preserves denial", async () => {
    const headers = { Authorization: "Bearer synthetic-token" };
    const fn = stub({}, false);
    expect(await fetchDashboardServer(7, "director", headers)).toBeNull();
    expect(fn).toHaveBeenCalledWith("http://127.0.0.1:8000/wms/dashboard?organization_id=7",
      { cache: "no-store", headers });
  });
  it("SSR maps scoped known-zero synthetic presentation data", async () => {
    const sample: Dashboard = { ...data(), alerts_count: 0, alerts_deficit_value: 0, inventory_value: 0,
      recon_max_diff_value: 0, recon_total_diff_value: 0, valuation_unavailable_reason: null };
    const fn = stub(sample);
    expect(await fetchDashboardServer(7, "sales")).toEqual(sample);
    expect(fn).toHaveBeenCalledWith("http://127.0.0.1:8000/wms/dashboard?organization_id=7",
      { cache: "no-store", headers: { "X-User-Roles": "sales" } });
  });
  it("SSR without roles preserves HTTP unknown", async () => {
    const fn = stub({}, false);
    expect(await fetchDashboardServer(7)).toBeNull();
    expect(fn).toHaveBeenCalledWith("http://127.0.0.1:8000/wms/dashboard?organization_id=7",
      { cache: "no-store", headers: undefined });
  });
  it("network failure stays unknown", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(Error("network")));
    expect(await fetchDashboardServer(7)).toBeNull(); expect(await fetchDashboard(7)).toBeNull();
  });
  it("client uses scoped no-store URL", async () => {
    const fn = stub(data()); const controller = new AbortController();
    expect(await fetchDashboard(7, controller.signal)).toEqual(data());
    expect(fn).toHaveBeenCalledWith("/api/wms/dashboard?organization_id=7",
      { cache: "no-store", signal: controller.signal });
  });
  it("invalid scope never fetches", async () => {
    const fn = stub(data());
    for (const id of [0, -1, 1.5, NaN, Number.MAX_SAFE_INTEGER + 1]) {
      expect(await fetchDashboard(id)).toBeNull(); expect(await fetchDashboardServer(id)).toBeNull();
    }
    expect(fn).not.toHaveBeenCalled();
  });
  it("foreign malformed or invalid counts rejected", async () => {
    for (const sample of [[], {}, null, { ...data(), organization_id: 8 },
      { ...data(), receipts_pending_qc: "3" }, { ...data(), tasks_pick_open: -1 },
      { ...data(), inventories_open: 0.5 }, { ...data(), movement_rows_today_in: Number.MAX_SAFE_INTEGER + 1 }]) {
      stub(sample); expect(await fetchDashboard(7)).toBeNull();
    }
  });
  it("period contradictions rejected", async () => {
    for (const patch of [{ report_date: "2026-02-30" }, { period_start: "2026-07-01T00:00:00Z" },
      { period_end: "2026-07-03T00:00:00" }, { period_start: "2026-06-30T00:00:00" },
      { period_basis: "UTC" }, { period_end: null }]) {
      stub({ ...data(), ...patch }); expect(await fetchDashboard(7)).toBeNull();
    }
  });
  it("financial known and unknown states must agree", async () => {
    for (const patch of [{ inventory_value: 0 }, { valuation_unavailable_reason: null },
      { valuation_unavailable_reason: "other" }, { gateway: "true" },
      { alerts_count: -1, valuation_unavailable_reason: null }]) {
      stub({ ...data(), ...patch }); expect(await fetchDashboard(7)).toBeNull();
    }
  });
  it("quantities without unit snapshots rejected", async () => {
    for (const patch of [{ movements_today_in: 0 }, { movements_today_out: 5 },
      { quantity_unavailable_reason: null }]) {
      stub({ ...data(), ...patch }); expect(await fetchDashboard(7)).toBeNull();
    }
  });
});
