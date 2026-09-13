import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { InvoiceDealPreparation } from "./invoice-deal-preparation";
import { loadOwnership } from "@/lib/deal-ownership-api";
const snapshot = { deal_id: 1, number: "D1", counterparty: "Display", owner_id: null, documents: [] };
const client = { id: 12, name: "Exact buyer", unp: "123", revision: 1, is_active: true, merged_into_id: null };
const bindingSnapshot = { organization_id: 7, deal: { id: 1, number: "D1", counterparty: "Display", owner_id: null }, client, documents: [] };
const response = (v: unknown, status = 200) => ({ ok: status < 400, status, json: async () => v }) as Response;
function fixture({ assigned = false, bound = false } = {}) {
  let owned = assigned, confirmed = bound;
  const fetcher = vi.fn(async (url: string, init?: RequestInit): Promise<Response> => {
    if (url.endsWith("ownership-preview")) return response({ assigned: owned, snapshot });
    if (url.endsWith("/ownership")) { owned = true; return response({ organization_id: 7, deal_id: 1, ...JSON.parse(init!.body as string), snapshot, evidence: "Ownership proof", actor: "chief" }); }
    if (url.includes("client-binding-preview")) return response({ assigned: false, snapshot: bindingSnapshot, binding: null });
    if (url.endsWith("/client-binding")) { confirmed = true; return response({ organization_id: 7, deal_id: 1, counterparty_id: 12, snapshot: bindingSnapshot, evidence: "Buyer proof", actor: "chief", created_at: "2026-09-10" }); }
    if (url.includes("/document-register?") && !owned) return response({}, 404);
    if (url.includes("/document-register?")) return response({ organization_id: 7, deal_id: 1, items: [], next_after_id: null,
      client_identity: confirmed ? { status: "confirmed", counterparty_id: 12, snapshot: client } : { status: "unresolved", counterparty_id: null },
      coverage: { sales_documents: "available", settlements: "separate_chief_register", shipments: "unavailable", tn_ttn: "not_connected" }, shipment_documents: [] });
    throw new Error(`Unexpected ${url}`);
  });
  vi.stubGlobal("fetch", fetcher); return fetcher;
}
function view(org = "7", dealId = "1", onReady = vi.fn()) { return <InvoiceDealPreparation org={org} dealId={dealId} onReady={onReady} onSelectOrg={vi.fn()} />; }
async function read() { fireEvent.click(await screen.findByText("Проверить принадлежность")); }
async function inspect() { await read(); await screen.findByRole("alert"); fireEvent.click(screen.getByText("Подтвердить новую принадлежность")); }
async function claim() {
  fireEvent.change(await screen.findByLabelText("Основание принадлежности организации"), { target: { value: "Ownership proof" } });
  fireEvent.click(screen.getByText("Подтвердить организацию сделки"));
}
beforeEach(() => sessionStorage.clear());
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("unbound converted deal requires both explicit confirmations with no hidden mutation", async () => {
  const fetcher = fixture(), ready = vi.fn(); render(view("7", "1", ready));
  await screen.findByText("Проверить принадлежность"); expect(fetcher).not.toHaveBeenCalled();
  await inspect(); await screen.findByLabelText("Основание принадлежности организации");
  expect(fetcher.mock.calls.filter(([, i]) => i?.method === "POST")).toHaveLength(0);
  await claim();
  fireEvent.change(await screen.findByLabelText("ID клиента для привязки"), { target: { value: "12" } });
  fireEvent.click(screen.getByText("Просмотреть привязку клиента"));
  fireEvent.change(await screen.findByLabelText("Основание привязки клиента"), { target: { value: "Buyer proof" } });
  fireEvent.click(screen.getByRole("button", { name: "Подтвердить клиента сделки" }));
  fireEvent.click(await screen.findByText("Продолжить к счёту"));
  expect(ready).toHaveBeenLastCalledWith(true);
  expect(fetcher.mock.calls.filter(([, i]) => i?.method === "POST").map(([u]) => u)).toEqual(["/api/sales/organizations/7/deals/1/ownership", "/api/sales/organizations/7/deals/1/client-binding"]);
});
it("existing binding needs no write and requires explicit continue", async () => {
  const f = fixture({ assigned: true, bound: true }), ready = vi.fn(); render(view("7", "1", ready)); await read();
  await screen.findByText(/Покупатель: Exact buyer/); expect(ready).not.toHaveBeenCalledWith(true);
  fireEvent.click(screen.getByText("Продолжить к счёту")); expect(ready).toHaveBeenLastCalledWith(true);
  expect(f.mock.calls.some(([, i]) => i?.method === "POST")).toBe(false);
  expect(f.mock.calls.some(([url]) => url.includes("ownership"))).toBe(false);
});
it.each([403, 404])("register %s does not imply unassigned and never triggers chief API automatically", async status => {
  const f = fixture(); f.mockResolvedValue(response({}, status)); render(view()); await read();
  expect(await screen.findByRole("alert")).toHaveTextContent(String(status));
  expect(f).toHaveBeenCalledOnce(); expect(f.mock.calls[0][0]).toContain("/document-register?");
  expect(screen.queryByLabelText("Основание принадлежности организации")).toBeNull();
  expect(screen.queryByText("Продолжить к счёту")).toBeNull();
});
it("non-chief 403 does not bypass ownership or create grants", async () => {
  const f = fixture(); f.mockResolvedValue(response({}, 403)); const ready = vi.fn(); render(view("7", "1", ready)); await inspect();
  expect(await screen.findByRole("alert")).toHaveTextContent("главному бухгалтеру");
  expect(f).toHaveBeenCalledTimes(2); expect(ready).not.toHaveBeenCalledWith(true);
});
it("definite stale 409 clears first claim and requires new preview", async () => {
  const f = fixture(); render(view()); await inspect(); await screen.findByLabelText("Основание принадлежности организации");
  f.mockResolvedValueOnce(response({}, 409)); await claim();
  expect(await screen.findByRole("alert")).toHaveTextContent("409"); expect(loadOwnership("1")).toBeNull();
  expect(screen.queryByText("Подтвердить организацию сделки")).toBeNull();
  expect(screen.getByText("Проверить принадлежность")).toBeEnabled();
});
it("unknown ownership survives reopen; later 409 retains exact command until successful retry", async () => {
  const f = fixture(); render(view()); await inspect(); await screen.findByLabelText("Основание принадлежности организации");
  f.mockRejectedValueOnce(new Error("lost")); await claim(); await screen.findByText("Повторить исходное подтверждение организации");
  const first = f.mock.calls.find(([, i]) => i?.method === "POST")!;
  cleanup(); render(view()); f.mockResolvedValueOnce(response({}, 409));
  fireEvent.click(await screen.findByText("Повторить исходное подтверждение организации")); await screen.findByRole("alert");
  expect(loadOwnership("1")?.body).toBe(first[1]!.body);
  fireEvent.click(screen.getByText("Повторить исходное подтверждение организации"));
  await screen.findByLabelText("ID клиента для привязки");
  const sends = f.mock.calls.filter(([, i]) => i?.method === "POST"); expect(sends).toHaveLength(3);
  expect(sends[1]).toEqual(first); expect(sends[2]).toEqual(first); expect(loadOwnership("1")).toBeNull();
});
it("pending ownership blocks another org after reopen", async () => {
  const f = fixture(); render(view()); await inspect(); await screen.findByLabelText("Основание принадлежности организации"); f.mockRejectedValueOnce(new Error("lost")); await claim();
  await screen.findByText("Повторить исходное подтверждение организации"); cleanup(); f.mockClear(); render(view("8"));
  await screen.findByText("Вернуться к организации #7"); expect(f).not.toHaveBeenCalled();
  expect(screen.queryByText("Проверить принадлежность")).toBeNull();
});
it.each(["org", "deal", "close"])("ignores late ownership preview after %s changes", async kind => {
  const f = fixture(), ready = vi.fn(); let resolve!: (v: Response) => void;
  const implementation = f.getMockImplementation()!; f.mockImplementation((url, init) => url.endsWith("ownership-preview") ? new Promise(r => { resolve = r; }) : implementation(url, init)); const v = render(view("7", "1", ready)); await inspect();
  v.rerender(kind === "close" ? <div /> : view(kind === "org" ? "8" : "7", kind === "deal" ? "2" : "1", ready));
  await act(async () => resolve(response({ assigned: true, snapshot })));
  expect(f).toHaveBeenCalledTimes(2); expect(ready).not.toHaveBeenCalledWith(true);
  expect(screen.queryByText(/Организация #7 подтверждена/)).toBeNull();
});
it("late ownership POST persists its result but does not load buyer into another deal", async () => {
  const f = fixture(), ready = vi.fn(); const v = render(view("7", "1", ready)); await inspect(); await screen.findByLabelText("Основание принадлежности организации");
  let resolve!: (v: Response) => void; f.mockImplementationOnce(() => new Promise(r => { resolve = r; })); await claim();
  v.rerender(view("7", "2", ready));
  await act(async () => resolve(response({ organization_id: 7, deal_id: 1, snapshot, evidence: "Ownership proof", actor: "chief" })));
  expect(f.mock.calls.filter(([u]) => u.includes("document-register?"))).toHaveLength(1);
  expect(ready).not.toHaveBeenCalledWith(true); expect(loadOwnership("1")).toBeNull();
});
it("failed buyer read never grants readiness from an earlier confirmed list", async () => {
  const f = fixture({ assigned: true, bound: true }), ready = vi.fn(); render(view("7", "1", ready)); await read();
  await screen.findByText("Продолжить к счёту"); f.mockResolvedValueOnce(response({}, 403));
  fireEvent.click(screen.getByText("Проверить подтверждённого покупателя")); await screen.findByRole("alert");
  expect(screen.queryByText("Продолжить к счёту")).toBeNull(); expect(ready).not.toHaveBeenCalledWith(true);
});
it.each(["org", "deal"])("ignores late confirmed buyer read after %s changes", async kind => {
  const f = fixture({ assigned: true, bound: true }), implementation = f.getMockImplementation()!, ready = vi.fn();
  let resolve!: (v: Response) => void;
  f.mockImplementation((url, init) => url.includes("/document-register?") ? new Promise(r => { resolve = r; }) : implementation(url, init));
  const v = render(view("7", "1", ready)); await read(); await waitFor(() => expect(resolve).toBeDefined());
  v.rerender(view(kind === "org" ? "8" : "7", kind === "deal" ? "2" : "1", ready));
  const result = await implementation("/api/sales/organizations/7/deals/1/document-register?after_id=0");
  await act(async () => resolve(result));
  expect(screen.queryByText(/Покупатель: Exact buyer/)).toBeNull();
  expect(screen.queryByText("Продолжить к счёту")).toBeNull(); expect(ready).not.toHaveBeenCalledWith(true);
});
