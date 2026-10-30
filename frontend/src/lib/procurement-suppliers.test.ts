import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createSupplier,
  emptySupplier,
  fetchSuppliers,
  fetchSuppliersServer,
  fetchSupplierScorecard,
  filterSuppliers,
  statusLabel,
  updateSupplier,
  type Supplier,
} from "@/lib/procurement-suppliers";

afterEach(() => vi.restoreAllMocks());

function stubFetch(data: unknown, ok = true) {
  const fn = vi.fn().mockResolvedValue({ ok, json: async () => data });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const S = (over: Partial<Supplier>): Supplier => ({
  id: 1,
  name: "Шэньчжэнь",
  unp: "ICN-1",
  country: "Китай",
  flag: "🇨🇳",
  contact_person: "",
  phone: "",
  email: "",
  payment_terms: "",
  lead_time_days: null,
  incoterms: "",
  status: "active",
  notes: "",
  ...over,
});

describe("statusLabel", () => {
  it("переводит статусы", () => {
    expect(statusLabel("active")).toBe("Активен");
    expect(statusLabel("blocked")).toBe("Заблокирован");
    expect(statusLabel("xxx")).toBe("xxx");
  });
});

describe("filterSuppliers", () => {
  const rows = [
    S({ id: 1, name: "Шэньчжэнь Бэттери", unp: "ICN-1", country: "Китай" }),
    S({ id: 2, name: "Минск Логистик", unp: "BY-9", country: "Беларусь" }),
  ];
  it("ищет по имени/УНП/стране, регистронезависимо", () => {
    expect(filterSuppliers(rows, "бэттери").map((s) => s.id)).toEqual([1]);
    expect(filterSuppliers(rows, "BY-9").map((s) => s.id)).toEqual([2]);
    expect(filterSuppliers(rows, "беларусь").map((s) => s.id)).toEqual([2]);
  });
  it("пустой запрос — все", () => {
    expect(filterSuppliers(rows, "  ")).toHaveLength(2);
  });
});

describe("emptySupplier", () => {
  it("даёт валидный пустой профиль (active, lead_time null)", () => {
    const e = emptySupplier();
    expect(e.status).toBe("active");
    expect(e.lead_time_days).toBeNull();
    expect(e.name).toBe("");
  });
});

describe("fetchSuppliersServer", () => {
  it("дёргает бэкенд напрямую с ролями в заголовке", async () => {
    const fn = stubFetch([S({ id: 1 })]);
    const result = await fetchSuppliersServer("procurement_head");
    expect(fn).toHaveBeenCalledWith("http://127.0.0.1:8000/procurement/suppliers", {
      cache: "no-store",
      headers: { "X-User-Roles": "procurement_head" },
    });
    expect(result).toEqual([S({ id: 1 })]);
  });

  it("без ролей — заголовков нет", async () => {
    const fn = stubFetch([]);
    await fetchSuppliersServer();
    expect(fn).toHaveBeenCalledWith("http://127.0.0.1:8000/procurement/suppliers", {
      cache: "no-store",
      headers: undefined,
    });
  });

  it("не ok — null: наличие поставщиков не подтверждено", async () => {
    stubFetch([S({ id: 1 })], false);
    expect(await fetchSuppliersServer()).toBeNull();
  });

  it("исключение сети — null: наличие поставщиков не подтверждено", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    expect(await fetchSuppliersServer()).toBeNull();
  });

  it("не принимает объект ошибки HTTP200 за серверный список", async () => {
    stubFetch({ detail: "PRIVATE_INTERNAL_DETAILS" });
    expect(await fetchSuppliersServer()).toBeNull();
  });
});

describe("fetchSuppliers", () => {
  it("не принимает объект ошибки HTTP200 за клиентский список", async () => {
    stubFetch({ detail: "PRIVATE_INTERNAL_DETAILS" });
    expect(await fetchSuppliers()).toBeNull();
  });
  it("ходит через прокси /api", async () => {
    const fn = stubFetch([S({ id: 2 })]);
    const result = await fetchSuppliers();
    expect(fn).toHaveBeenCalledWith("/api/procurement/suppliers", { cache: "no-store" });
    expect(result).toEqual([S({ id: 2 })]);
  });

  it("не ok — null (чтобы не затереть SSR-данные)", async () => {
    stubFetch([S({ id: 1 })], false);
    expect(await fetchSuppliers()).toBeNull();
  });

  it("исключение сети — null", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")));
    expect(await fetchSuppliers()).toBeNull();
  });
});

describe("fetchSupplierScorecard", () => {
  const card = { organization_id: 7, supplier_id: 3, supplier_name: "Поставщик",
    orders_count: 2, on_time_observed_count: 1, on_time_count: 1, on_time_rate: 1,
    won_rfq_count: 0, avg_won_price_byn: null, claims_total: null, claims_open: null,
    claims_closed: null, score: null, status: "provisional_claims_unattributed",
    reason: "Claims unattributed" };

  it("читает только выбранное юрлицо и проверяет его в ответе", async () => {
    const fn = stubFetch(card);
    expect(await fetchSupplierScorecard(7, 3)).toEqual(card);
    expect(fn).toHaveBeenCalledWith("/api/procurement/organizations/7/suppliers/3/scorecard", { cache: "no-store" });
    stubFetch({ ...card, organization_id: 8 });
    await expect(fetchSupplierScorecard(7, 3)).rejects.toThrow("Некорректные показатели");
  });

  it("отвергает сводный балл и фиктивный ноль претензий", async () => {
    stubFetch({ ...card, claims_total: 0, score: 80 });
    await expect(fetchSupplierScorecard(7, 3)).rejects.toThrow("Некорректные показатели");
  });
});

describe("createSupplier", () => {
  it("POST с JSON-телом", async () => {
    const input = emptySupplier();
    const fn = stubFetch(S({ id: 3 }));
    const result = await createSupplier(input);
    expect(fn).toHaveBeenCalledWith("/api/procurement/suppliers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    expect(result).toEqual(S({ id: 3 }));
  });

  it("не ok — null", async () => {
    stubFetch(null, false);
    expect(await createSupplier(emptySupplier())).toBeNull();
  });

  it("исключение сети — null", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")));
    expect(await createSupplier(emptySupplier())).toBeNull();
  });
});

describe("updateSupplier", () => {
  it("PATCH по id с частичным телом", async () => {
    const patch = { status: "blocked" };
    const fn = stubFetch(S({ id: 4, status: "blocked" }));
    const result = await updateSupplier(7, patch);
    expect(fn).toHaveBeenCalledWith("/api/procurement/suppliers/7", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    expect(result).toEqual(S({ id: 4, status: "blocked" }));
  });

  it("не ok — null", async () => {
    stubFetch(null, false);
    expect(await updateSupplier(7, { status: "blocked" })).toBeNull();
  });

  it("исключение сети — null", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")));
    expect(await updateSupplier(7, {})).toBeNull();
  });
});
