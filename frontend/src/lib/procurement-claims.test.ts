import { afterEach, describe, expect, it, vi } from "vitest";

import {
  type Claim,
  claimCounts,
  claimStatusLabel,
  claimStatusTone,
  claimTypeLabel,
  createClaim,
  fetchClaims,
  fetchClaimsServer,
  filterClaims,
  sourceLabel,
  updateClaim,
} from "@/lib/procurement-claims";

afterEach(() => vi.restoreAllMocks());

function mockFetch(impl: (...args: unknown[]) => Promise<unknown>) {
  global.fetch = vi.fn(impl) as unknown as typeof fetch;
}

function claim(over: Partial<Claim> = {}): Claim {
  return {
    id: 1,
    supplier: "",
    supplier_id: null,
    item: "АКБ 48V 100Ah",
    reason: "Непропай БМС",
    order_code: "№250",
    claim_type: "брак",
    qty_affected: 0,
    amount_byn: null,
    resolution: "",
    status: "open",
    source: "production",
    entity_ref: "production:qc:1",
    ...over,
  };
}

describe("procurement-claims", () => {
  it("claimStatusLabel: подписи статусов", () => {
    expect(claimStatusLabel("open")).toBe("Открыта");
    expect(claimStatusLabel("resolved")).toBe("Решена");
    expect(claimStatusLabel("rejected")).toBe("Отклонена");
  });

  it("claimStatusTone: тон по статусу", () => {
    expect(claimStatusTone("open")).toContain("amber");
    expect(claimStatusTone("resolved")).toContain("green");
    expect(claimStatusTone("rejected")).toContain("slate");
  });

  it("sourceLabel: источник претензии", () => {
    expect(sourceLabel("production")).toBe("Брак производства");
    expect(sourceLabel("manual")).toBe("manual");
    expect(sourceLabel("")).toBe("—");
  });

  it("claimCounts: всего/открыто/решено/без поставщика", () => {
    const claims = [
      claim({ id: 1, status: "open", supplier: "" }), // открыта, без поставщика
      claim({ id: 2, status: "open", supplier: "ООО Поставщик" }), // открыта, с поставщиком
      claim({ id: 3, status: "resolved", supplier: "ООО Поставщик" }),
    ];
    expect(claimCounts(claims)).toEqual({
      total: 3,
      open: 2,
      resolved: 1,
      withoutSupplier: 1,
    });
    expect(claimCounts([])).toEqual({ total: 0, open: 0, resolved: 0, withoutSupplier: 0 });
  });

  it("claimTypeLabel: тип или прочерк", () => {
    expect(claimTypeLabel("недопоставка")).toBe("недопоставка");
    expect(claimTypeLabel("")).toBe("—");
  });

  it("filterClaims: по статусу/типу/строке", () => {
    const claims = [
      claim({ id: 1, status: "open", claim_type: "брак", item: "АКБ" }),
      claim({ id: 2, status: "resolved", claim_type: "недопоставка", item: "Зарядка" }),
      claim({ id: 3, status: "open", claim_type: "недопоставка", item: "АКБ доп" }),
    ];
    expect(filterClaims(claims, { status: "open" }).map((c) => c.id)).toEqual([1, 3]);
    expect(filterClaims(claims, { type: "недопоставка" }).map((c) => c.id)).toEqual([2, 3]);
    expect(filterClaims(claims, { query: "акб" }).map((c) => c.id)).toEqual([1, 3]);
    expect(filterClaims(claims, { status: "open", type: "недопоставка" }).map((c) => c.id)).toEqual([3]);
    expect(filterClaims(claims, {})).toHaveLength(3);
  });

  it("fetchClaimsServer: 200 → список; шлёт заголовок ролей и cache:no-store", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => [claim({ id: 5 })] }));
    mockFetch(f);
    const result = await fetchClaimsServer("procurement");
    expect(result).toEqual([claim({ id: 5 })]);
    expect(f).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/procurement/claims",
      expect.objectContaining({
        cache: "no-store",
        headers: { "X-User-Roles": "procurement" },
      }),
    );
  });

  it("fetchClaimsServer: без ролей — заголовки undefined", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => [] }));
    mockFetch(f);
    await fetchClaimsServer();
    expect(f).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/procurement/claims",
      expect.objectContaining({ headers: undefined }),
    );
  });

  it("fetchClaimsServer: HTTP-ошибка → []", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchClaimsServer()).toEqual([]);
  });

  it("fetchClaimsServer: исключение → []", async () => {
    mockFetch(async () => {
      throw new Error("net");
    });
    expect(await fetchClaimsServer()).toEqual([]);
  });

  it("fetchClaims: 200 → список через прокси /api", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => [claim({ id: 9 })] }));
    mockFetch(f);
    expect(await fetchClaims()).toEqual([claim({ id: 9 })]);
    expect(f).toHaveBeenCalledWith(
      "/api/procurement/claims",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("fetchClaims: HTTP-ошибка → []", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchClaims()).toEqual([]);
  });

  it("fetchClaims: исключение → []", async () => {
    mockFetch(async () => {
      throw new Error("net");
    });
    expect(await fetchClaims()).toEqual([]);
  });

  it("updateClaim: PATCH на /api/procurement/claims/{id} с телом и заголовком JSON", async () => {
    const updated = claim({ id: 3, status: "resolved", supplier: "ООО Поставщик" });
    const f = vi.fn(async () => ({ ok: true, json: async () => updated }));
    mockFetch(f);
    const result = await updateClaim(3, { status: "resolved", supplier: "ООО Поставщик" });
    expect(result).toEqual(updated);
    expect(f).toHaveBeenCalledWith(
      "/api/procurement/claims/3",
      expect.objectContaining({
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "resolved", supplier: "ООО Поставщик" }),
      }),
    );
  });

  it("updateClaim: HTTP-ошибка → null", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await updateClaim(1, { status: "rejected" })).toBeNull();
  });

  it("updateClaim: исключение → null", async () => {
    mockFetch(async () => {
      throw new Error("net");
    });
    expect(await updateClaim(1, { status: "rejected" })).toBeNull();
  });

  it("createClaim: POST на /api/procurement/claims с телом ввода", async () => {
    const input = { item: "АКБ", reason: "Брак", claim_type: "брак", qty_affected: 2 };
    const created = claim({ id: 42, ...input });
    const f = vi.fn(async () => ({ ok: true, json: async () => created }));
    mockFetch(f);
    const result = await createClaim(input);
    expect(result).toEqual(created);
    expect(f).toHaveBeenCalledWith(
      "/api/procurement/claims",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input),
      }),
    );
  });

  it("createClaim: HTTP-ошибка → null", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await createClaim({ item: "x" })).toBeNull();
  });

  it("createClaim: исключение → null", async () => {
    mockFetch(async () => {
      throw new Error("net");
    });
    expect(await createClaim({ item: "x" })).toBeNull();
  });
});
