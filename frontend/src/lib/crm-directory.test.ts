import { afterEach, describe, expect, it, vi } from "vitest";
import { loadDirectory } from "./crm-directory";

const client = { id: 1, name: "Client", unp: null, is_active: true, deal_id: 7 };
const contact = { id: 2, full_name: "Person", phone: null, email: null,
  is_primary: false, counterparty_id: 1, counterparty_name: "Client", deal_id: null };
afterEach(() => vi.unstubAllGlobals());
function response(data: unknown, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue({ ok: status < 300, status, json: async () => data });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("CRM directory HTTP contract", () => {
  it("uses the authenticated proxy with encoded filters and no cache", async () => {
    const fetchMock = response({ rows: [client], total: 51 });
    const signal = new AbortController().signal;
    expect(await loadDirectory("clients", "A & B", 50, signal)).toEqual({ status: "ok", rows: [client], total: 51 });
    expect(fetchMock).toHaveBeenCalledWith("/api/sales/clients?q=A+%26+B&offset=50&limit=50", { cache: "no-store", signal });
  });
  it("accepts contacts and actual empty pages", async () => {
    response({ rows: [contact], total: 1 });
    expect((await loadDirectory("contacts", "", 0)).status).toBe("ok");
    response({ rows: [], total: 0 });
    expect(await loadDirectory("contacts", "", 0)).toEqual({ status: "ok", rows: [], total: 0 });
  });
  it.each([[401, "unauthorized"], [403, "forbidden"], [500, "error"]])("distinguishes HTTP %i", async (code, status) => {
    response({}, Number(code));
    expect(await loadDirectory("clients", "", 0)).toEqual({ status });
  });
  it.each([
    null, {}, { rows: null, total: 0 }, { rows: [client], total: -1 },
    { rows: [client], total: "1" }, { rows: [client], total: 0 },
    { rows: [{ ...client, deal_id: "7" }], total: 1 },
    { rows: [{ ...client, deal_id: -1 }], total: 1 },
    { rows: [{ ...client, id: 1.5 }], total: 1 },
    { rows: [{ ...client, id: Number.MAX_SAFE_INTEGER + 1 }], total: 1 },
    { rows: [client, client], total: 2 }, { rows: [contact], total: 1 },
  ])("rejects malformed client responses", async (data) => {
    response(data);
    expect(await loadDirectory("clients", "", 0)).toEqual({ status: "error" });
  });
  it("rejects a foreign row shape or malformed parent ID for contacts", async () => {
    response({ rows: [client], total: 1 });
    expect((await loadDirectory("contacts", "", 0)).status).toBe("error");
    response({ rows: [{ ...contact, counterparty_id: 0 }], total: 1 });
    expect((await loadDirectory("contacts", "", 0)).status).toBe("error");
  });
  it("rejects network and JSON errors without false empty data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));
    expect((await loadDirectory("clients", "", 0)).status).toBe("error");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => { throw new Error("json"); } }));
    expect((await loadDirectory("clients", "", 0)).status).toBe("error");
  });
});
