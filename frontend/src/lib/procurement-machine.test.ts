
function milestones(target: string) {
  const stages = ["collection", "payment", "production", "to_cn_warehouse", "to_minsk", "customs"]; const durations = [28, 7, 14, 7, 20, 7]; let day = new Date(target);
  const result = stages.map((stage, seq) => ({ stage, title: stage, seq, duration_days: durations[seq], planned_date: "", actual_date: null }));
  for (const m of [...result].reverse()) { m.planned_date = day.toISOString().slice(0, 10); day = new Date(day.getTime() - m.duration_days * 86400000); } return { milestones: result, start_date: day.toISOString().slice(0, 10) };
}
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { canonical, commandHash, decimalInput, emptyLine, fetchOrder, fetchCustomerDeadlines, fetchExpectedReservations, fetchLandedPreview, fetchPlan, sendEdit, validCommand, validOutcome, MutationUnknown, type EditCommand, type EditOutcome } from "./procurement-machine";
const scope = { organization_id: 2, principal: "alice", can_manage: true };
const command = (): EditCommand => ({ version: 1, request_key: "11111111-1111-4111-8111-111111111111", order_id: 7, action: "add_line", payload: { ...emptyLine(), sku_code: "A" } });
const detail = () => ({ organization_id: 2, id: 7, number: "PO7", supplier: "S", status: "draft", eta_date: null, freight_byn: "0.00", lines: [], next_after_line_id: null });
const plan = () => ({ organization_id: 2, order_id: 7, principal: "alice", transport_method_code: "truck", target_arrival_date: "2026-12-01", start_date: null, total_days: 83, ...milestones("2026-12-01"), customer_requirements_status: "unverified", at_risk: null, at_risk_deals: [], required_by: null, required_arrival: null, slack_days: null, schedule_start_in_past: null });
async function receipt(c = command(), rejected = false): Promise<EditOutcome> {
  const common = { version: 1 as const, organization_id: 2, principal: "alice", request_key: c.request_key, command_hash: await commandHash(c), order_id: 7, action: c.action };
  return rejected ? { ...common, outcome: "rejected", code: "command_abandoned", no_business_write: true } : { ...common, outcome: "applied", ownership_id: 9, effect: { line: { id: 12, ...c.payload } } };
}
let f: ReturnType<typeof vi.fn>; const ok = (body: unknown, status = 200) => ({ ok: status === 200, status, json: async () => body });
beforeEach(() => { f = vi.fn(); vi.stubGlobal("fetch", f); }); afterEach(() => vi.unstubAllGlobals());
it("reads scoped detail without global SSR", async () => { f.mockResolvedValue(ok(detail())); expect(await fetchOrder(2, 7)).toEqual(detail()); expect(f.mock.calls[0][0]).toBe("/api/procurement/organizations/2/orders/7?after_line_id=0"); });
it.each([403, 404, 503])("read failure %s is not an empty order", async status => { f.mockResolvedValue({ ok: false, status }); await expect(fetchOrder(2, 7)).rejects.toThrow(String(status)); });
it("reads all 201 lines without losing the tail", async () => { const lines = Array.from({ length: 200 }, (_, i) => ({ id: i + 1, ...emptyLine() })); f.mockResolvedValueOnce(ok({ ...detail(), lines, next_after_line_id: 200 })).mockResolvedValueOnce(ok({ ...detail(), lines: [{ id: 201, ...emptyLine() }] })); expect((await fetchOrder(2, 7)).lines).toHaveLength(201); expect(f.mock.calls[1][0]).toContain("after_line_id=200"); });
it("rejects duplicate lines, wrong org and nonadvancing cursor", async () => { for (const patch of [{ lines: [{ id: 1, ...emptyLine() }, { id: 1, ...emptyLine() }] }, { organization_id: 9 }, { next_after_line_id: 0 }]) { f.mockResolvedValue(ok({ ...detail(), ...patch })); await expect(fetchOrder(2, 7)).rejects.toThrow(); } });
it("scoped preview preserves decimal strings", async () => { const v = { organization_id: 2, order_id: 7, freight_byn: "1.00", total_goods_byn: "2.00", total_landed_byn: "3.00", lines: [] }; f.mockResolvedValue(ok(v)); expect(await fetchLandedPreview(2, 7)).toEqual(v); expect(f.mock.calls[0][0]).toContain("organizations/2/orders/7/landed-preview"); });
it("accepts exact conversion capacity in the expected-reserve projection", async () => {
  const v = { organization_id: 2, order_id: 7, lines: [{ pending_conversion_count: 1, order_line_id: 11, sku_code: "A", ordered: "20.00", accepted: "12.00", warehouse_accepted: "10.00", physical_convertible: "6.00", expected: "8.00", converted: "4.00", convertible: "8.00", expected_reserved: "6.00", free_expected: "2.00", uncovered: "0.00", reservations: [{ id: 3, deal_id: 9, demand_id: null, document_id: 10, qty: "10.00", released: "0.00", converted: "4.00", convertible: "8.00" }] }] };
  f.mockResolvedValue(ok(v)); expect(await fetchExpectedReservations(2, 7)).toEqual(v); expect(f.mock.calls[0][0]).toContain("organizations/2/expected-reservations/order/7");
});
it("rejects an expected-reserve projection that omits conversion fields", async () => {
  const v = { organization_id: 2, order_id: 7, lines: [{ order_line_id: 11, sku_code: "A", ordered: "20.00", accepted: "12.00", expected: "8.00", expected_reserved: "6.00", free_expected: "2.00", uncovered: "0.00", reservations: [] }] };
  f.mockResolvedValue(ok(v)); await expect(fetchExpectedReservations(2, 7)).rejects.toThrow();
});
it("does not accept false green customer risk", async () => { f.mockResolvedValue(ok({ ...plan(), at_risk: false })); await expect(fetchPlan(2, 7)).rejects.toThrow(); });
it("sends one frozen body and UUID for execute and reconcile with context headers", async () => { const c = command(); const r = await receipt(c); f.mockResolvedValue(ok(r)); expect(await sendEdit(scope, c, "execute")).toEqual(r); expect(await sendEdit(scope, c, "reconcile")).toEqual(r); expect(f.mock.calls[1][0]).toBe("/api/procurement/organizations/2/orders/7/edit-commands/reconcile"); expect(f.mock.calls[0][1].body).toBe(f.mock.calls[1][1].body); for (const [, init] of f.mock.calls) expect(init.headers).toMatchObject({ "X-Expected-Organization": "2", "X-Expected-Principal": "alice" }); });
it("accepts a fully validated terminal tombstone, not generic409", async () => { const c = command(); f.mockResolvedValue(ok(await receipt(c, true), 409)); expect((await sendEdit(scope, c, "reconcile")).outcome).toBe("rejected"); f.mockResolvedValue(ok({ detail: "conflict" }, 409)); await expect(sendEdit(scope, c, "execute")).rejects.toBeInstanceOf(MutationUnknown); });
it.each([403, 422, 500, 503])("generic%s does not close pending", async status => { f.mockResolvedValue(ok({ detail: "error" }, status)); await expect(sendEdit(scope, command(), "execute")).rejects.toBeInstanceOf(MutationUnknown); });
it("network loss never automatically retries", async () => { f.mockRejectedValue(new Error("lost")); await expect(sendEdit(scope, command(), "execute")).rejects.toBeInstanceOf(MutationUnknown); expect(f).toHaveBeenCalledTimes(1); });
it.each(["organization_id", "principal", "request_key", "command_hash", "order_id", "action", "ownership_id", "effect", "version"])("missing receipt field %s fails actual validator", async field => { const r = await receipt(); delete (r as unknown as Record<string, unknown>)[field]; expect(await validOutcome(r, scope, command())).toBe(false); });
it("wrong payload effect, extra keys and bad line ID fail", async () => { const r = await receipt(); for (const patch of [{ effect: { line: { id: 12, ...command().payload, qty: "9.00" } } }, { extra: true }, { effect: { line: { id: 0, ...command().payload } } }, { principal: "bob" }]) expect(await validOutcome({ ...r, ...patch }, scope, command())).toBe(false); });
it("every action validates its own historical effect", async () => {
  for (const [action, payload, effect] of [
    ["delete_line", { line_id: 12 }, { line: { id: 12, ...emptyLine(), sku_code: "DELETED" } }],
    ["header", { freight_byn: "3.13" }, { before: { freight_byn: "1.00" }, after: { freight_byn: "3.13" } }],
    ["status", { status: "ordered" }, { from: "draft", to: "ordered", received_at: null, event_ids: [1] }],
    ["plan", { transport_method_code: "truck", target_arrival_date: "2026-12-01" }, plan()],
  ] as const) {
    const c = { ...command(), action, payload }; const r = { ...await receipt(c), effect };
    expect(validCommand(c)).toBe(true); expect(await validOutcome(r, scope, c)).toBe(true);
    expect(await validOutcome({ ...r, effect: { ...effect, surprise: 1 } }, scope, c)).toBe(false);
  }
});
it("canonical hash matches independent Python vector and ignores key ordering", async () => {
  const c = command(); const reversed = Object.fromEntries(Object.entries(c).reverse()) as EditCommand; reversed.payload = Object.fromEntries(Object.entries(c.payload).reverse());
  expect(await commandHash(c)).toBe("72f9ddc0263a1ceb2af323b74ea4bbc6db32cf62a2b4a7cae7699e4a0bdacc7f"); expect(await commandHash(reversed)).toBe(await commandHash(c)); expect(canonical({ z: "🙂", a: "Русский" })).toBe('{"a":"Русский","z":"🙂"}');
});

it("exact decimal input is not float-rounded", () => { expect(decimalInput("999999999999.99", 2)).toBe("999999999999.99"); expect(decimalInput("1", 4)).toBe("1.0000"); for (const value of ["-1", "1e2", "NaN", "0.001", "1000000000000.00"]) expect(() => decimalInput(value, 2)).toThrow(); });
it("rejects malformed frozen commands before HTTP", async () => { const c = { ...command(), payload: { ...command().payload, qty: 1 } }; expect(validCommand(c)).toBe(false); await expect(sendEdit(scope, c, "execute")).rejects.toThrow(); expect(f).not.toHaveBeenCalled(); });


async function landedReceipt(kind = "received-status") {
  const atomic = kind === "atomic-save";
  const empty = kind === "empty-status";
  const c: EditCommand = { ...command(), action: atomic ? "save" : "status",
    payload: atomic ? { status: { status: "received" } } : { status: empty ? "ordered" : "received" } };
  const receivedAt = "2026-10-01T12:00:00";
  const payload = { sku_code: "A", organization_id: 2, purchase_order_id: 7,
    stage: "actual", currency: "BYN", entity_ref: "purchase_order:7", shipment_id: "SYNTHETIC",
    unit_landed_cost_byn: "0.5050", qty: "2.00", total_landed_byn: "1.01",
    fx_rate: null, fx_date: null, fx_rate_basis: null,
    calculation: { version: 1, received_at: receivedAt, freight_byn: "0.00", duty_pct: null,
      lines: [{ id: 1, sku_code: "A", qty: "2.00", goods_value_byn: "1.01", weight: "0.000", volume: "0.0000" },
        // Valid historical snapshots can include lines ignored by the allocation.
        { id: 2, sku_code: "", qty: "0.00", goods_value_byn: "0.00", weight: "0.000", volume: "0.0000" },
        { id: 3, sku_code: "OLD", qty: "-1.00", goods_value_byn: "-1.00", weight: "-1.000", volume: "0.0000" }] } };
  const status = { from: empty ? "draft" : "customs", to: empty ? "ordered" : "received",
    received_at: empty ? null : receivedAt, event_ids: empty ? [10] : [10, 11],
    landed: empty ? [] : [{ event_id: 11, payload }] };
  const r = { ...await receipt(c), effect: atomic ? { status } : status };
  return { c, r, status };
}

it.each(["empty-status", "received-status", "atomic-save"])("accepts verified landed receipt %s", async kind => {
  const { c, r } = await landedReceipt(kind);
  f.mockResolvedValue(ok(r));
  for (const mode of ["execute", "reconcile"] as const) expect(await sendEdit(scope, c, mode)).toEqual(r);
  expect(f).toHaveBeenCalledTimes(2);
  expect(f.mock.calls[0][1].body).toBe(f.mock.calls[1][1].body);
});

it.each(["foreign-org", "wrong-po", "unknown-event", "duplicate-event", "duplicate-sku", "wrong-currency", "malformed-calculation", "extra-key"])("rejects malformed landed receipt %s without closing pending", async fault => {
  const { c, r, status } = await landedReceipt();
  const item = status.landed[0];
  if (fault === "foreign-org") item.payload.organization_id = 9;
  if (fault === "wrong-po") item.payload.purchase_order_id = 8;
  if (fault === "unknown-event") item.event_id = 999;
  if (fault === "duplicate-event") status.landed.push(structuredClone(item));
  if (fault === "duplicate-sku") { status.event_ids.push(12); status.landed.push({ ...structuredClone(item), event_id: 12 }); }
  if (fault === "wrong-currency") item.payload.currency = "USD";
  if (fault === "malformed-calculation") Object.assign(item.payload.calculation.lines[0], { qty: "NaN" });
  if (fault === "extra-key") Object.assign(item.payload, { unexpected: true });
  f.mockResolvedValue(ok(r));
  for (const mode of ["execute", "reconcile"] as const) await expect(sendEdit(scope, c, mode)).rejects.toBeInstanceOf(MutationUnknown);
  expect(f).toHaveBeenCalledTimes(2); // one request per explicit action; never auto-retry
  expect(f.mock.calls[0][1].body).toBe(f.mock.calls[1][1].body);
});


function customerReview() {
  return { organization_id: 2, order_id: 7, status: "live_review", source: "outstanding_expected_reservations",
    earliest_required_arrival: "2026-12-28", unresolved_deadlines: 0, complete_customer_demand: false, at_risk: true,
    items: [{ reservation_id: 11, deal_id: 21, sku_code: "A", outstanding_qty: "1.00",
      ship_deadline: "2026-12-31", required_arrival: "2026-12-28", deadline_status: "dated", at_risk: true }] };
}
it("reads signed live slack and preserves known zero versus unknown penalties", async () => {
  const legacy = customerReview();
  const value = { ...legacy, slack_days: -4, items: [{ ...legacy.items[0], deal_number: "SD-21",
    slack_days: -4, penalty_rate_pct: "0.00", penalty_cap_pct: null, penalty_terms: null }] };
  f.mockResolvedValue(ok(value));
  expect(await fetchCustomerDeadlines(2, 7)).toEqual(value);
  expect(f.mock.calls[0][0]).toBe("/api/procurement/organizations/2/orders/7/customer-deadlines");
});
it("keeps older deadline responses readable without inventing metadata", async () => {
  const value = customerReview(); f.mockResolvedValue(ok(value));
  expect(await fetchCustomerDeadlines(2, 7)).toEqual(value);
});
it.each([
  ["slack_days", 1.5, false], ["deal_number", {}, true], ["penalty_rate_pct", "NaN", true],
  ["penalty_cap_pct", "-1.00", true], ["penalty_terms", {}, true],
])("rejects malformed optional deadline metadata %s", async (field, value, item) => {
  const review = customerReview();
  const bad = item ? { ...review, items: [{ ...review.items[0], [String(field)]: value }] }
    : { ...review, [String(field)]: value };
  f.mockResolvedValue(ok(bad));
  await expect(fetchCustomerDeadlines(2, 7)).rejects.toThrow("Некорректные сведения");
});
