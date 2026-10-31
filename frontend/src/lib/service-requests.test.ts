import { afterEach, describe, expect, it, vi } from "vitest";
import { createServiceRequest, loadServiceRequests, serviceCard, serviceStages, updateServiceRequest } from "./service-requests";

const row = { id: 7, title: "Synthetic service request", description: "Synthetic description", status: "new", priority: "normal", counterparty_id: 42, deal_id: 77, created_at: "2026-10-30T10:20:00" };
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
function mock(value: unknown = [row], status = 200) {
  const request = vi.fn().mockResolvedValue(response(value, status)); vi.stubGlobal("fetch", request); return request;
}
afterEach(() => vi.unstubAllGlobals());

describe("native service API contract", () => {
  it("reads the native array and preserves unknown statuses without fictitious money or owners", async () => {
    const request = mock([row, { ...row, id: 8, status: "external_review" }]);
    const rows = await loadServiceRequests();
    expect(request).toHaveBeenCalledWith("/api/service/requests", expect.objectContaining({ cache: "no-store" }));
    expect(serviceStages(rows).find((s) => s.id === "external_review")?.cards[0].id).toBe(8);
    expect(serviceStages(rows).find((s) => s.id === "done")?.count).toBe(0);
    expect(serviceCard(rows[0])).toMatchObject({ amount: null, progress: null, owner: "", insight: "" });
  });
  it("accepts empty native lists but refuses stages envelopes, malformed rows and duplicate IDs", async () => {
    mock([]); expect(await loadServiceRequests()).toEqual([]);
    for (const body of [{ stages: [] }, [{ ...row, id: -1 }], [row, row], [{ ...row, counterparty_id: "42" }]]) {
      mock(body); await expect(loadServiceRequests()).rejects.toMatchObject({ kind: "read" });
    }
  });
  it("classifies 401 and 403 as access loss without exposing the server body", async () => {
    for (const status of [401, 403]) {
      mock({ detail: "SYNTHETIC-PRIVATE-ERROR" }, status);
      await expect(loadServiceRequests()).rejects.toMatchObject({ kind: "auth", message: "auth" });
    }
  });
  it("does not turn HTTP failure or network failure into zero requests", async () => {
    mock({}, 502); await expect(loadServiceRequests()).rejects.toMatchObject({ kind: "read" });
    vi.mocked(fetch).mockRejectedValue(new Error("network"));
    await expect(loadServiceRequests()).rejects.toMatchObject({ kind: "read" });
  });
  it("creates with schema fields only and requires a matching native acknowledgment", async () => {
    const request = mock(row, 201);
    expect(await createServiceRequest({ title: ` ${row.title} `, description: row.description, priority: "normal" })).toEqual(row);
    expect(JSON.parse(request.mock.calls[0][1].body)).toEqual({ title: row.title, description: row.description, priority: "normal" });
    expect(request.mock.calls[0][1].method).toBe("POST");
  });
  it("rejects an empty title, invalid priority or ID before any write", async () => {
    const request = mock(row);
    await expect(createServiceRequest({ title: " ", description: "", priority: "normal" })).rejects.toMatchObject({ kind: "rejected" });
    await expect(createServiceRequest({ title: "Synthetic", description: "", priority: "unrecognized" })).rejects.toMatchObject({ kind: "rejected" });
    await expect(updateServiceRequest(-1, { status: "done" })).rejects.toMatchObject({ kind: "rejected" });
    expect(request).not.toHaveBeenCalled();
  });
  it("separates rejected writes from lost or unverifiable acknowledgments", async () => {
    mock({ detail: "SYNTHETIC-PRIVATE-ERROR" }, 422);
    await expect(createServiceRequest(row)).rejects.toMatchObject({ kind: "rejected", message: "rejected" });
    vi.mocked(fetch).mockRejectedValue(new Error("lost ACK"));
    await expect(createServiceRequest(row)).rejects.toMatchObject({ kind: "uncertain" });
    mock({ ...row, title: "Different synthetic request" }, 201);
    await expect(createServiceRequest(row)).rejects.toMatchObject({ kind: "uncertain" });
  });
  it("patches status and priority using the native schema, never stage", async () => {
    const request = mock({ ...row, status: "in_progress", priority: "high" });
    await updateServiceRequest(7, { status: "in_progress", priority: "high" });
    expect(request.mock.calls[0][0]).toBe("/api/service/requests/7");
    expect(JSON.parse(request.mock.calls[0][1].body)).toEqual({ status: "in_progress", priority: "high" });
    expect(request.mock.calls[0][1].method).toBe("PATCH");
  });
  it("does not accept a patch acknowledgment for another ID or unchanged status/priority", async () => {
    for (const value of [{ ...row, id: 99, status: "done" }, row]) {
      mock(value); await expect(updateServiceRequest(7, { status: "done" })).rejects.toMatchObject({ kind: "uncertain" });
    }
    mock(row); await expect(updateServiceRequest(7, { priority: "high" })).rejects.toMatchObject({ kind: "uncertain" });
  });
});
