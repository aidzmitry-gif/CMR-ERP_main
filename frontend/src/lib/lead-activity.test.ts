import { afterEach, describe, expect, it, vi } from "vitest";
import { readActivityMessages, readActivityTasks } from "./lead-activity";

const task = { id: 1, deal_id: 4, title: "Позвонить", kind: "call", due_at: null, status: "open", overdue: false };
const message = { id: 2, channel: "email", direction: "out", author: "Менеджер", text: "Запись", created_at: "2026-09-13T10:00:00" };
afterEach(() => vi.unstubAllGlobals());

describe("linked deal activity transport", () => {
  it("uses authenticated proxy, no-store and cancellation for both real endpoints", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => [task] })
      .mockResolvedValueOnce({ ok: true, json: async () => [message] });
    vi.stubGlobal("fetch", fetcher);
    const signal = new AbortController().signal;
    expect(await readActivityTasks(4, signal)).toEqual({ status: "ok", rows: [task] });
    expect(await readActivityMessages(4, signal)).toEqual({ status: "ok", rows: [message] });
    expect(fetcher.mock.calls).toEqual([
      ["/api/sales/deals/4/tasks", { cache: "no-store", signal }],
      ["/api/sales/deals/4/messages", { cache: "no-store", signal }],
    ]);
  });
  it.each([0, -1, NaN, 1.2, Number.MAX_SAFE_INTEGER + 1])("does not fetch invalid ID %s", async (id) => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    expect((await readActivityTasks(id)).status).toBe("error");
    expect((await readActivityMessages(id)).status).toBe("error");
    expect(fetcher).not.toHaveBeenCalled();
  });
  it.each([[401, "access"], [403, "access"], [404, "missing"], [500, "request"]])("keeps HTTP %s distinct from empty", async (status, reason) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status }));
    expect(await readActivityTasks(4)).toEqual({ status: "error", reason });
    expect(await readActivityMessages(4)).toEqual({ status: "error", reason });
  });
  it("distinguishes network failure from successful empty data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ ok: true, json: async () => [] }));
    expect(await readActivityTasks(4)).toEqual({ status: "error", reason: "request" });
    expect(await readActivityTasks(4)).toEqual({ status: "ok", rows: [] });
  });
  it.each([{}, [null], [{ ...task, deal_id: 5 }], [{ ...task, status: "wrong" }], [{ ...task, status: ["done"] }], [task, task]])("rejects malformed or cross-deal tasks %j", async (rows) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => rows }));
    expect(await readActivityTasks(4)).toEqual({ status: "error", reason: "malformed" });
  });
  it.each([[{ ...message, id: -2 }], [{ ...message, text: null }], [message, message]])("rejects malformed messages %j", async (rows) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => rows }));
    expect(await readActivityMessages(4)).toEqual({ status: "error", reason: "malformed" });
  });
});
