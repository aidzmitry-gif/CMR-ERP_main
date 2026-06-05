import { afterEach, describe, expect, it, vi } from "vitest";
import { createFunnelCard, fetchFunnelBoard, moveFunnelCard } from "@/lib/funnel-api";

afterEach(() => vi.restoreAllMocks());

function mockFetch(impl: (...args: unknown[]) => Promise<unknown>) {
  global.fetch = vi.fn(impl) as unknown as typeof fetch;
}

describe("funnel-api", () => {
  it("fetchFunnelBoard возвращает стадии при 200", async () => {
    mockFetch(async () => ({ ok: true, json: async () => ({ stages: [{ id: "a" }] }) }));
    expect(await fetchFunnelBoard("/x/board")).toEqual([{ id: "a" }]);
  });

  it("fetchFunnelBoard при HTTP-ошибке → []", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchFunnelBoard("/x/board")).toEqual([]);
  });

  it("fetchFunnelBoard без поля stages → []", async () => {
    mockFetch(async () => ({ ok: true, json: async () => ({}) }));
    expect(await fetchFunnelBoard("/x/board")).toEqual([]);
  });

  it("fetchFunnelBoard при исключении → []", async () => {
    mockFetch(async () => {
      throw new Error("net");
    });
    expect(await fetchFunnelBoard("/x/board")).toEqual([]);
  });

  it("createFunnelCard шлёт POST через /api и возвращает true", async () => {
    const f = vi.fn(async () => ({ ok: true }));
    mockFetch(f);
    expect(await createFunnelCard("/proc/requests", { a: 1 })).toBe(true);
    expect(f).toHaveBeenCalledWith("/api/proc/requests", expect.objectContaining({ method: "POST" }));
  });

  it("createFunnelCard при исключении → false", async () => {
    mockFetch(async () => {
      throw new Error("x");
    });
    expect(await createFunnelCard("/x", {})).toBe(false);
  });

  it("moveFunnelCard шлёт PATCH с телом {stage} и возвращает true", async () => {
    const f = vi.fn(async () => ({ ok: true }));
    mockFetch(f);
    expect(await moveFunnelCard("/proc/requests", 5, "qc")).toBe(true);
    expect(f).toHaveBeenCalledWith("/api/proc/requests/5", expect.objectContaining({ method: "PATCH" }));
  });

  it("moveFunnelCard при исключении → false", async () => {
    mockFetch(async () => {
      throw new Error("x");
    });
    expect(await moveFunnelCard("/x", 5, "qc")).toBe(false);
  });
});
