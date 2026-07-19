import { afterEach, describe, expect, it, vi } from "vitest";

import {
  approveNorm,
  createNorm,
  deleteNorm,
  fetchNorms,
  fetchNormsServer,
  filterByKind,
  formatNh,
  type Norm,
  normCounts,
  normKindLabel,
  normStatusLabel,
  updateNorm,
} from "@/lib/production-norms";

afterEach(() => vi.restoreAllMocks());

function stubFetch(data: unknown, ok = true) {
  const fn = vi.fn().mockResolvedValue({ ok, json: async () => data });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const apiNorm: Norm = {
  id: 5,
  kind: "product",
  title: "Кожух",
  nh: 3.5,
  status: "approved",
  note: "прим",
};

function norm(over: Partial<Norm>): Norm {
  return { id: 1, kind: "product", title: "Изделие", nh: 0, status: "none", note: "", ...over };
}

describe("production-norms", () => {
  it("formatNh: русский формат, целое без дробной, ноль → тире", () => {
    expect(formatNh(10)).toBe("10");
    expect(formatNh(7.5)).toBe("7,5");
    expect(formatNh(0)).toBe("—");
    expect(formatNh(0.5)).toBe("0,5");
    expect(formatNh(40)).toBe("40");
  });

  it("normStatusLabel: подписи статусов", () => {
    expect(normStatusLabel("none")).toBe("Нет нормы");
    expect(normStatusLabel("pending")).toBe("На утверждении");
    expect(normStatusLabel("approved")).toBe("Утверждена");
  });

  it("normKindLabel: подписи видов", () => {
    expect(normKindLabel("product")).toBe("Изделие");
    expect(normKindLabel("operation")).toBe("Операция");
  });

  it("filterByKind: отбор по виду", () => {
    const norms = [
      norm({ id: 1, kind: "product" }),
      norm({ id: 2, kind: "operation" }),
      norm({ id: 3, kind: "product" }),
    ];
    expect(filterByKind(norms, "product").map((n) => n.id)).toEqual([1, 3]);
    expect(filterByKind(norms, "operation").map((n) => n.id)).toEqual([2]);
  });

  it("normCounts: счётчики для KPI", () => {
    const norms = [
      norm({ id: 1, status: "approved" }),
      norm({ id: 2, status: "pending" }),
      norm({ id: 3, status: "pending" }),
      norm({ id: 4, status: "none" }),
    ];
    expect(normCounts(norms)).toEqual({ total: 4, pending: 2, none: 1, approved: 1 });
  });

  it("normCounts: пустой справочник", () => {
    expect(normCounts([])).toEqual({ total: 0, pending: 0, none: 0, approved: 0 });
  });

  it("fetchNormsServer: SSR-запрос к BACKEND_URL с ролями, маппинг ответа", async () => {
    const fetchMock = stubFetch([apiNorm]);
    const result = await fetchNormsServer("sales_head");
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8000/production/norms", {
      cache: "no-store",
      headers: { "X-User-Roles": "sales_head" },
    });
    expect(result).toEqual([apiNorm]);
  });

  it("fetchNormsServer: без ролей — заголовки не заданы", async () => {
    const fetchMock = stubFetch([]);
    await fetchNormsServer();
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8000/production/norms", {
      cache: "no-store",
      headers: undefined,
    });
  });

  it("fetchNormsServer: !ok → пустой массив", async () => {
    stubFetch(null, false);
    expect(await fetchNormsServer()).toEqual([]);
  });

  it("fetchNormsServer: сеть упала → пустой массив", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await fetchNormsServer()).toEqual([]);
  });

  it("fetchNorms: без kind — без query, через прокси /api", async () => {
    const fetchMock = stubFetch([apiNorm]);
    const result = await fetchNorms();
    expect(fetchMock).toHaveBeenCalledWith("/api/production/norms", { cache: "no-store" });
    expect(result).toEqual([apiNorm]);
  });

  it("fetchNorms: с kind — query-параметр", async () => {
    const fetchMock = stubFetch([apiNorm]);
    await fetchNorms("operation");
    expect(fetchMock).toHaveBeenCalledWith("/api/production/norms?kind=operation", {
      cache: "no-store",
    });
  });

  it("fetchNorms: !ok → пустой массив", async () => {
    stubFetch(null, false);
    expect(await fetchNorms()).toEqual([]);
  });

  it("fetchNorms: сеть упала → пустой массив", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await fetchNorms()).toEqual([]);
  });

  it("createNorm: POST с JSON-телом, маппинг ответа", async () => {
    const fetchMock = stubFetch(apiNorm);
    const input = { title: "Кожух", kind: "product" as const, nh: 3.5, note: "прим" };
    const result = await createNorm(input);
    expect(fetchMock).toHaveBeenCalledWith("/api/production/norms", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    expect(result).toEqual(apiNorm);
  });

  it("createNorm: !ok → null", async () => {
    stubFetch(null, false);
    expect(await createNorm({ title: "x" })).toBeNull();
  });

  it("createNorm: сеть упала → null", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await createNorm({ title: "x" })).toBeNull();
  });

  it("updateNorm: PATCH по id с телом-патчем", async () => {
    const fetchMock = stubFetch(apiNorm);
    const patch = { nh: 4 };
    const result = await updateNorm(5, patch);
    expect(fetchMock).toHaveBeenCalledWith("/api/production/norms/5", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    expect(result).toEqual(apiNorm);
  });

  it("updateNorm: !ok → null", async () => {
    stubFetch(null, false);
    expect(await updateNorm(5, { nh: 1 })).toBeNull();
  });

  it("updateNorm: сеть упала → null", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await updateNorm(5, { nh: 1 })).toBeNull();
  });

  it("approveNorm: POST на /approve, true при ok", async () => {
    const fetchMock = stubFetch(null, true);
    const result = await approveNorm(5);
    expect(fetchMock).toHaveBeenCalledWith("/api/production/norms/5/approve", { method: "POST" });
    expect(result).toBe(true);
  });

  it("approveNorm: !ok → false (напр. 409 без значения нормы)", async () => {
    stubFetch(null, false);
    expect(await approveNorm(5)).toBe(false);
  });

  it("approveNorm: сеть упала → false", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await approveNorm(5)).toBe(false);
  });

  it("deleteNorm: DELETE по id, true при ok", async () => {
    const fetchMock = stubFetch(null, true);
    const result = await deleteNorm(5);
    expect(fetchMock).toHaveBeenCalledWith("/api/production/norms/5", { method: "DELETE" });
    expect(result).toBe(true);
  });

  it("deleteNorm: !ok → false", async () => {
    stubFetch(null, false);
    expect(await deleteNorm(5)).toBe(false);
  });

  it("deleteNorm: сеть упала → false", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("net")));
    expect(await deleteNorm(5)).toBe(false);
  });
});
