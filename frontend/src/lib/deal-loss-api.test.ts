import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { beginLossCommand, dispatchLoss, fetchLossContext, fetchLossPreview, hash, lossGate,
  readLossJournal, recoverLoss, validateRecord, validateResolution, type LossScope, type RequestBody } from "./deal-loss-api";

const scope: LossScope = { deal: 1, org: 7, principal: "seller" };
const key = "12345678-1234-1234-1234-123456789abc";
const context = { deal_id: 1, principal: "seller", organization_id: 7, organization: { id: 7, name: "Book", unp: "123" },
  mapping_required: false, funnel: "repeat_clients", stage: "rp_new", lost_stage: "rp_lost", pending_request_id: null,
  latest_request_id: null, latest_request_state: null };
const snapshot = { funnel: "repeat_clients", stage: "rp_new", lost_stage: "rp_lost", invoices: [] };
const ok = (v: unknown) => ({ ok: true, status: 200, json: async () => v });
beforeEach(() => { sessionStorage.clear(); vi.stubGlobal("crypto", webcrypto); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function fixture() {
  const body: RequestBody = { organization_id: 7, request_key: key, expected_composition_digest: await hash(snapshot),
    reason_code: "price", comment: null, finalize_if_empty: false };
  const base = { id: key, organization_id: 7, deal_id: 1, command: body, command_hash: await hash(body), snapshot, actor: "seller" };
  const record = { ...base, request_id: key, request_digest: await hash(base), state: "pending", resolution: null,
    invoices: [], ready_to_finalize: true };
  return { body, record };
}
it("sends exactly the durable normalized body and server principal header", async () => {
  const { body, record } = await fixture();
  const fetcher = vi.fn(async (url: string) => ok(url.endsWith("loss-context") ? context : record)); vi.stubGlobal("fetch", fetcher);
  const j = await beginLossCommand(scope, "request", body, key, null);
  expect(fetcher).not.toHaveBeenCalled();
  const result = await dispatchLoss(j, true);
  expect(result.record?.request_id).toBe(key);
  expect(result.journal.attempt?.outcome).toBe("done");
  expect(fetcher).toHaveBeenCalledWith("/api/sales/deals/1/lose", expect.objectContaining({ method: "POST",
    headers: { "Content-Type": "application/json", "X-Expected-Principal": "seller" }, body: j.attempt!.body }));
  expect(fetcher).toHaveBeenLastCalledWith("/api/sales/deals/1/loss-context", { cache: "no-store" });
});
it("network uncertainty survives reload and only replays the original UUID/body", async () => {
  const { body, record } = await fixture(); let lost = true;
  const fetcher = vi.fn(async (url: string) => {
    if (url.endsWith("loss-context")) return ok(context);
    if (lost) throw new Error("connection lost");
    return ok(record);
  }); vi.stubGlobal("fetch", fetcher);
  const original = await beginLossCommand(scope, "request", body, key, null);
  await expect(dispatchLoss(original, true)).rejects.toThrow("неизвестен");
  const saved = await readLossJournal(scope);
  expect(saved.attempt?.outcome).toBe("uncertain");
  await expect(beginLossCommand(scope, "request", { ...body, request_key: crypto.randomUUID() }, key, saved.raw)).rejects.toThrow("исходной");
  lost = false; await dispatchLoss(saved);
  const posts = fetcher.mock.calls.filter(([url]) => url.endsWith("/lose"));
  expect(posts).toHaveLength(2);
  expect((fetcher.mock.calls as unknown as [string, RequestInit][]).filter(([url]) => url.endsWith("/lose"))[1][1].body).toBe(original.attempt!.body);
});
it("wrong-scope 200 is uncertain, never a success", async () => {
  const { body, record } = await fixture();
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ok(url.endsWith("loss-context") ? context : { ...record, deal_id: 2 })));
  const j = await beginLossCommand(scope, "request", body, key, null);
  await expect(dispatchLoss(j, true)).rejects.toThrow("сверка");
  expect((await readLossJournal(scope)).attempt?.outcome).toBe("uncertain");
});
it("rechecks principal before POST, leaving the original journal intact", async () => {
  const { body } = await fixture();
  const fetcher = vi.fn(async () => ok({ ...context, principal: "another" })); vi.stubGlobal("fetch", fetcher);
  const j = await beginLossCommand(scope, "request", body, key, null);
  await expect(dispatchLoss(j, true)).rejects.toThrow("Пользователь");
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect((await readLossJournal(scope)).raw).toBe(j.raw);
  expect((await readLossJournal({ ...scope, principal: "another" })).attempt).toBeNull();
});
it("refuses a command if storage cannot be written", async () => {
  const { body } = await fixture(); const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  vi.stubGlobal("sessionStorage", { getItem: () => null, setItem: () => { throw new Error("quota"); } });
  await expect(beginLossCommand(scope, "request", body, key, null)).rejects.toThrow("не сохраняется");
  expect(fetcher).not.toHaveBeenCalled();
});
it("refuses corrupt storage rather than inventing a new command", async () => {
  const { body } = await fixture(); const j = await beginLossCommand(scope, "request", body, key, null);
  const storageKey = sessionStorage.key(0)!; sessionStorage.setItem(storageKey, j.raw!.replace('"price"', '"other"'));
  // Body is a serialized string; alter the bound hash unambiguously.
  sessionStorage.setItem(storageKey, JSON.stringify({ ...j.attempt, hash: "0".repeat(64) }));
  await expect(readLossJournal(scope)).rejects.toThrow("повреждена");
});
it("CAS blocks replacement during the preflight await", async () => {
  const { body } = await fixture(); let resolve!: (v: unknown) => void;
  const fetcher = vi.fn(() => new Promise(r => { resolve = r; })); vi.stubGlobal("fetch", fetcher);
  const j = await beginLossCommand(scope, "request", body, key, null);
  const sent = dispatchLoss(j, true);
  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledOnce());
  sessionStorage.setItem(sessionStorage.key(0)!, JSON.stringify({ ...j.attempt, nonce: crypto.randomUUID() }));
  resolve(ok(context));
  await expect(sent).rejects.toThrow("изменилась");
  expect(fetcher).toHaveBeenCalledOnce();
});
it("can recover a persisted request via GET without sending again", async () => {
  const { body, record } = await fixture();
  const fetcher = vi.fn(async (url: string) => ok(url.endsWith("loss-context") ? context : record)); vi.stubGlobal("fetch", fetcher);
  const j = await beginLossCommand(scope, "request", body, key, null);
  const result = await recoverLoss(j);
  expect(result.journal.attempt?.outcome).toBe("done");
  expect(fetcher.mock.calls.map(([url]) => url)).toEqual(["/api/sales/deals/1/loss-context", `/api/sales/organizations/7/deals/1/loss-requests/${key}`, "/api/sales/deals/1/loss-context"]);
});
it.each([403, 409, "principal"])("keeps committed POST uncertain after final scope failure %s", async failure => {
  const { body, record } = await fixture(); let committed = false;
  const fetcher = vi.fn(async (url: string) => {
    if (!url.endsWith("loss-context")) { committed = true; return ok(record); }
    if (!committed) return ok(context);
    return failure === "principal" ? ok({ ...context, principal: "another" }) : { ok: false, status: failure };
  });
  vi.stubGlobal("fetch", fetcher);
  const original = await beginLossCommand(scope, "request", body, key, null);
  await expect(dispatchLoss(original, true)).rejects.toThrow();
  const saved = await readLossJournal(scope);
  expect(saved.attempt?.outcome).toBe("uncertain");
  expect(saved.attempt?.body).toBe(original.attempt?.body);
  await expect(beginLossCommand(scope, "request", { ...body, request_key: crypto.randomUUID() }, key, saved.raw)).rejects.toThrow("исходной");
  fetcher.mockImplementation(async url => ok(url.endsWith("loss-context") ? context : record));
  expect((await dispatchLoss(saved)).journal.attempt?.outcome).toBe("done");
  expect(fetcher.mock.calls.filter(([url]) => url.endsWith("/lose"))).toHaveLength(2);
});
it("does not settle recovery when the current principal changes during the GET", async () => {
  const { body, record } = await fixture(); let received = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (!url.endsWith("loss-context")) { received = true; return ok(record); }
    return ok(received ? { ...context, principal: "another" } : context);
  }));
  const j = await beginLossCommand(scope, "request", body, key, null);
  await expect(recoverLoss(j)).rejects.toThrow("Пользователь");
  expect((await readLossJournal(scope)).raw).toBe(j.raw);
});
it("known first 409 permits an explicit new preview, but an uncertain retry stays uncertain", async () => {
  const { body } = await fixture();
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("loss-context") ? ok(context) : { ok: false, status: 409 }));
  const j = await beginLossCommand(scope, "request", body, key, null);
  await expect(dispatchLoss(j, true)).rejects.toThrow("409");
  expect((await readLossJournal(scope)).attempt?.outcome).toBe("rejected");
  const nextKey = crypto.randomUUID(); const saved = await readLossJournal(scope);
  const next = await beginLossCommand(scope, "request", { ...body, request_key: nextKey }, nextKey, saved.raw);
  await expect(dispatchLoss(next)).rejects.toThrow("409");
  expect((await readLossJournal(scope)).attempt?.outcome).toBe("uncertain");
});
it("checks server composition digest and exact identities", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ok({ organization_id: 7, deal_id: 1, snapshot,
    composition_digest: "0".repeat(64), pending_request_id: null, invoices: [] })));
  await expect(fetchLossPreview(scope)).rejects.toThrow("сверка");
  vi.stubGlobal("fetch", vi.fn(async () => ok({ ...context, organization: { id: 99, name: "Forged", unp: "x" } })));
  await expect(fetchLossContext(1)).rejects.toThrow("сверка");
});
it("validates immutable request and resolution hashes", async () => {
  const { record } = await fixture();
  await expect(validateRecord({ ...record, actor: "forged" }, scope)).rejects.toThrow("сверка");
  await expect(validateResolution({ resolution_id: key, request_id: key, digest: "0".repeat(64) }, scope)).rejects.toThrow("сверка");
});
it.each(["rp_lost", "custom_rejected"])("routes %s by current funnel semantics", async target => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ok(url.endsWith("loss-context") ? context
    : [{ code: "custom_rejected", funnel: "repeat_clients", kind: "lost", is_active: true }])));
  expect(await lossGate("1", target)).toBe(true);
});
