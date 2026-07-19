import { afterEach, describe, expect, it, vi } from "vitest";

import {
  addRateVersion,
  archiveNomenclatureGroup,
  archiveSimpleRef,
  buildCategoryTree,
  bulkUpsertRef,
  changedFields,
  createNomenclatureGroup,
  createSimpleRef,
  currencyRateAsOf,
  decideApproval,
  fetchAiCatalog,
  fetchAllSkus,
  fetchCounterpartyCard,
  fetchCurrencyRates,
  fetchDuplicateClusters,
  fetchNomenclatureGroups,
  fetchPendingReferenceApprovals,
  fetchQualityDetail,
  fetchQualitySummary,
  fetchReferenceCatalog,
  fetchRefRowsByEndpoint,
  fetchRefRowsByKey,
  fetchSimpleRef,
  fetchSkuCard,
  fetchSkuLandedInputs,
  fetchSkusByCategory,
  fetchSurvivorshipRules,
  fetchSyncJournal,
  fetchTnvedRates,
  fetchVatRates,
  flattenCatalog,
  isCurrentVersion,
  mergeCounterparties,
  parseRefCsv,
  patchNomenclatureGroup,
  patchSimpleRef,
  qualityTone,
  rowsFromResult,
  runReferenceQuery,
  sortVersionsDesc,
  totalDuplicates,
  unmergeCounterparty,
  type NomenclatureGroup,
  type ReferenceCatalog,
  type ReferenceMeta,
  type SkuVersionRow,
} from "./reference-data";

afterEach(() => vi.restoreAllMocks());

function mockFetch(impl: (...args: unknown[]) => Promise<unknown>) {
  global.fetch = vi.fn(impl) as unknown as typeof fetch;
}

const BASE = "http://127.0.0.1:8000";

function version(over: Partial<SkuVersionRow> = {}): SkuVersionRow {
  return {
    start_date: "2026-01-01",
    end_date: null,
    title: "Реле 12В",
    unit: "шт",
    category_id: 1,
    weight_kg: 0.2,
    tnved_code: "8536490000",
    shelf_life_days: null,
    attributes: {},
    ...over,
  };
}

function meta(key: string): ReferenceMeta {
  return {
    key,
    title: key,
    module: "core",
    endpoint: `/system/refs/${key}`,
    owner_schema: "public",
    columns: [],
    permissions: [],
    archivable: true,
    versioned: false,
    ai_exposed: false,
    description: "",
  };
}

describe("flattenCatalog", () => {
  it("разворачивает отделы в плоский список с прикреплённым department", () => {
    const catalog: ReferenceCatalog = {
      departments: {
        Система: [meta("core.units"), meta("core.currencies")],
        Продажи: [meta("sales.stages")],
      },
    };
    const flat = flattenCatalog(catalog);
    expect(flat).toHaveLength(3);
    expect(flat.find((r) => r.key === "sales.stages")?.department).toBe("Продажи");
    expect(flat.filter((r) => r.department === "Система")).toHaveLength(2);
  });

  it("пустой каталог → пустой список", () => {
    expect(flattenCatalog({ departments: {} })).toEqual([]);
  });
});

describe("isCurrentVersion", () => {
  it("текущая — без даты окончания (end_date=null)", () => {
    expect(isCurrentVersion({ end_date: null })).toBe(true);
    expect(isCurrentVersion({ end_date: "2026-05-01" })).toBe(false);
  });
});

describe("sortVersionsDesc", () => {
  it("сортирует версии по убыванию start_date (новая — первой), не мутируя вход", () => {
    const rows = [
      { start_date: "2026-01-01", rate: 3.18 },
      { start_date: "2026-05-01", rate: 3.25 },
      { start_date: "2026-03-01", rate: 3.21 },
    ];
    const sorted = sortVersionsDesc(rows);
    expect(sorted.map((r) => r.start_date)).toEqual(["2026-05-01", "2026-03-01", "2026-01-01"]);
    expect(rows[0].start_date).toBe("2026-01-01"); // исходный массив не тронут
  });
});

describe("totalDuplicates", () => {
  it("считает кандидатов сверх эталона по всем кластерам", () => {
    const clusters = [
      { unp: "111", members: [{ id: 1, name: "A" }, { id: 2, name: "A дубль" }] },
      { unp: "222", members: [{ id: 3, name: "B" }, { id: 4, name: "B2" }, { id: 5, name: "B3" }] },
    ];
    expect(totalDuplicates(clusters)).toBe(3); // (2-1) + (3-1)
  });

  it("нет кластеров → 0", () => {
    expect(totalDuplicates([])).toBe(0);
  });
});

describe("parseRefCsv", () => {
  it("парсит по колонкам, отбрасывает строку-заголовок", () => {
    const out = parseRefCsv("code,title\nPCS,штука\nKG,килограмм", ["code", "title"]);
    expect(out).toEqual([
      { code: "PCS", title: "штука" },
      { code: "KG", title: "килограмм" },
    ]);
  });

  it("пустая ячейка опускается, parent_id приводится к числу", () => {
    const out = parseRefCsv("C1,Группа,\nC2,Под,1", ["code", "name", "parent_id"]);
    expect(out[0]).toEqual({ code: "C1", name: "Группа" });
    expect(out[1]).toEqual({ code: "C2", name: "Под", parent_id: 1 });
  });

  it("поддерживает таб как разделитель", () => {
    expect(parseRefCsv("X\tикс", ["code", "title"])).toEqual([{ code: "X", title: "икс" }]);
  });
});

describe("qualityTone", () => {
  it("пороги: ≥0.95 ок · ≥0.8 warn · иначе bad", () => {
    expect(qualityTone(1)).toBe("ok");
    expect(qualityTone(0.95)).toBe("ok");
    expect(qualityTone(0.9)).toBe("warn");
    expect(qualityTone(0.8)).toBe("warn");
    expect(qualityTone(0.5)).toBe("bad");
  });
});

describe("buildCategoryTree", () => {
  const groups: NomenclatureGroup[] = [
    { id: 1, code: "CAT-0100", name: "Электронные компоненты", parent_id: null, is_active: true },
    { id: 2, code: "CAT-0102", name: "Микросхемы", parent_id: 1, is_active: true },
    { id: 3, code: "CAT-0103", name: "Резисторы", parent_id: 1, is_active: true },
    { id: 4, code: "CAT-0200", name: "Кабельная продукция", parent_id: null, is_active: true },
  ];

  it("собирает дерево из плоского списка по parent_id, сохраняя порядок", () => {
    const tree = buildCategoryTree(groups);
    expect(tree.map((n) => n.code)).toEqual(["CAT-0100", "CAT-0200"]);
    const electronics = tree[0];
    expect(electronics.children.map((n) => n.code)).toEqual(["CAT-0102", "CAT-0103"]);
    expect(tree[1].children).toEqual([]);
  });

  it("сирота (родитель отсутствует) поднимается в корень, не теряется", () => {
    const orphan: NomenclatureGroup[] = [
      { id: 9, code: "CAT-9", name: "Сирота", parent_id: 999, is_active: true },
    ];
    expect(buildCategoryTree(orphan).map((n) => n.code)).toEqual(["CAT-9"]);
  });

  it("пустой список → пустое дерево", () => {
    expect(buildCategoryTree([])).toEqual([]);
  });
});

describe("changedFields", () => {
  it("самая ранняя версия (older=null) → пусто", () => {
    expect(changedFields(version(), null)).toEqual([]);
  });

  it("изменения типизированных полей помечаются подписями", () => {
    const older = version({ title: "Реле 12В", weight_kg: 0.2 });
    const newer = version({ title: "Реле 12В (2 шт)", weight_kg: 0.25 });
    expect(changedFields(newer, older)).toEqual(["Наименование", "Вес, кг"]);
  });

  it("без изменений → пусто", () => {
    expect(changedFields(version(), version())).toEqual([]);
  });

  it("изменения в свободных attributes — по ключу", () => {
    const older = version({ attributes: { Производитель: "Omron" } });
    const newer = version({ attributes: { Производитель: "TE", Корпус: "DIP" } });
    expect(changedFields(newer, older).sort()).toEqual(["Корпус", "Производитель"]);
  });
});

describe("fetchReferenceCatalog", () => {
  it("200 → каталог из тела ответа", async () => {
    const catalog = { departments: { Система: [] } };
    mockFetch(async () => ({ ok: true, json: async () => catalog }));
    expect(await fetchReferenceCatalog()).toEqual(catalog);
  });

  it("роль → заголовок X-User-Roles; URL — system/references", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => ({ departments: {} }) }));
    mockFetch(f);
    await fetchReferenceCatalog("sales_head");
    expect(f).toHaveBeenCalledWith(
      `${BASE}/system/references`,
      expect.objectContaining({ headers: { "X-User-Roles": "sales_head" } }),
    );
  });

  it("без роли — заголовки не передаются", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => ({ departments: {} }) }));
    mockFetch(f);
    await fetchReferenceCatalog();
    expect(f).toHaveBeenCalledWith(`${BASE}/system/references`, expect.objectContaining({ headers: undefined }));
  });

  it("не-200 → { departments: {} }", async () => {
    mockFetch(async () => ({ ok: false, status: 500 }));
    expect(await fetchReferenceCatalog()).toEqual({ departments: {} });
  });

  it("исключение сети → { departments: {} }", async () => {
    mockFetch(async () => {
      throw new Error("net");
    });
    expect(await fetchReferenceCatalog()).toEqual({ departments: {} });
  });
});

describe("fetchAiCatalog", () => {
  it("200 → тело ответа", async () => {
    const cat = { tool: { name: "t", endpoint: "/e", params: [], note: "" }, references: [] };
    mockFetch(async () => ({ ok: true, json: async () => cat }));
    expect(await fetchAiCatalog()).toEqual(cat);
  });

  it("URL — /system/references/ai-catalog", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => ({}) }));
    mockFetch(f);
    await fetchAiCatalog();
    expect(f).toHaveBeenCalledWith(`${BASE}/system/references/ai-catalog`, expect.anything());
  });

  it("не-200 → null", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchAiCatalog()).toBeNull();
  });

  it("исключение → null", async () => {
    mockFetch(async () => {
      throw new Error("x");
    });
    expect(await fetchAiCatalog()).toBeNull();
  });
});

describe("runReferenceQuery", () => {
  it("шлёт POST на /api/system/references/query с телом input", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => ({ ref: "core.skus", result: [] }) }));
    mockFetch(f);
    const input = { ref: "core.skus", category_id: 3, limit: 10 };
    const res = await runReferenceQuery(input);
    expect(f).toHaveBeenCalledWith(
      "/api/system/references/query",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input),
      }),
    );
    expect(res).toEqual({ ref: "core.skus", result: [] });
  });

  it("не-200 → null", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await runReferenceQuery({ ref: "x" })).toBeNull();
  });

  it("исключение → null", async () => {
    mockFetch(async () => {
      throw new Error("x");
    });
    expect(await runReferenceQuery({ ref: "x" })).toBeNull();
  });
});

describe("fetchSkusByCategory", () => {
  it("зовёт reference.query с ref=core.skus, category_id, limit; маппит result", async () => {
    const rows = [{ code: "A1", title: "Реле", unit: "шт", category_id: 3, vat_code: "20" }];
    const f = vi.fn(async () => ({ ok: true, json: async () => ({ ref: "core.skus", result: rows }) }));
    mockFetch(f);
    const res = await fetchSkusByCategory(3, 20);
    expect(f).toHaveBeenCalledWith(
      "/api/system/references/query",
      expect.objectContaining({
        body: JSON.stringify({ ref: "core.skus", category_id: 3, limit: 20 }),
      }),
    );
    expect(res).toEqual(rows);
  });

  it("дефолтный limit = 50", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => ({ result: [] }) }));
    mockFetch(f);
    await fetchSkusByCategory(7);
    expect(f).toHaveBeenCalledWith(
      "/api/system/references/query",
      expect.objectContaining({ body: JSON.stringify({ ref: "core.skus", category_id: 7, limit: 50 }) }),
    );
  });

  it("нет результата → []", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchSkusByCategory(1)).toEqual([]);
  });
});

describe("fetchAllSkus", () => {
  it("POST на /system/references/query с ref=core.skus и CATALOG_ROW_LIMIT по умолчанию", async () => {
    const rows = [{ code: "X", title: "Т", unit: null, category_id: null, vat_code: null }];
    const f = vi.fn(async () => ({ ok: true, json: async () => ({ result: rows }) }));
    mockFetch(f);
    const res = await fetchAllSkus("sales");
    expect(f).toHaveBeenCalledWith(
      `${BASE}/system/references/query`,
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-Roles": "sales" },
        body: JSON.stringify({ ref: "core.skus", limit: 250 }),
      }),
    );
    expect(res).toEqual(rows);
  });

  it("свой limit прокидывается в тело", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => ({ result: [] }) }));
    mockFetch(f);
    await fetchAllSkus(undefined, 10);
    expect(f).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ body: JSON.stringify({ ref: "core.skus", limit: 10 }) }),
    );
  });

  it("не-200 → []", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchAllSkus()).toEqual([]);
  });

  it("исключение → []", async () => {
    mockFetch(async () => {
      throw new Error("x");
    });
    expect(await fetchAllSkus()).toEqual([]);
  });
});

describe("rowsFromResult", () => {
  it("result-массив → массив как есть", () => {
    expect(rowsFromResult({ result: [{ a: 1 }] })).toEqual([{ a: 1 }]);
  });
  it("result не массив/отсутствует/null-конверт → []", () => {
    expect(rowsFromResult({ result: "x" })).toEqual([]);
    expect(rowsFromResult({})).toEqual([]);
    expect(rowsFromResult(null)).toEqual([]);
  });
});

describe("fetchPendingReferenceApprovals", () => {
  it("URL включает status=pending, фильтрует по kind=reference.change", async () => {
    const all = [
      { id: 1, kind: "reference.change", entity_ref: "r1", subject: "s", route: "rop", status: "pending", requested_by: "u", created_at: null, due_at: null },
      { id: 2, kind: "deal.discount", entity_ref: "r2", subject: "s2", route: "rop", status: "pending", requested_by: "u", created_at: null, due_at: null },
    ];
    const f = vi.fn(async () => ({ ok: true, json: async () => all }));
    mockFetch(f);
    const res = await fetchPendingReferenceApprovals();
    expect(f).toHaveBeenCalledWith(`${BASE}/approvals?status=pending`, expect.anything());
    expect(res).toEqual([all[0]]);
  });

  it("не-200 → []", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchPendingReferenceApprovals()).toEqual([]);
  });
});

describe("decideApproval", () => {
  it("approve=true → POST /api/approvals/:id/approve с reason", async () => {
    const f = vi.fn(async () => ({ ok: true }));
    mockFetch(f);
    const res = await decideApproval(7, true, "ok");
    expect(f).toHaveBeenCalledWith(
      "/api/approvals/7/approve",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ reason: "ok" }) }),
    );
    expect(res).toBe(true);
  });

  it("approve=false → .../reject, reason по умолчанию null", async () => {
    const f = vi.fn(async () => ({ ok: true }));
    mockFetch(f);
    await decideApproval(7, false);
    expect(f).toHaveBeenCalledWith(
      "/api/approvals/7/reject",
      expect.objectContaining({ body: JSON.stringify({ reason: null }) }),
    );
  });

  it("исключение → false", async () => {
    mockFetch(async () => {
      throw new Error("x");
    });
    expect(await decideApproval(1, true)).toBe(false);
  });
});

describe("bulkUpsertRef", () => {
  it("шлёт rows+dry_run на /api/system/refs/:table/bulk, возвращает тело", async () => {
    const plan = { dry_run: true, would_create: [], would_update: [], conflicts: [] };
    const f = vi.fn(async () => ({ ok: true, json: async () => plan }));
    mockFetch(f);
    const rows = [{ code: "X" }];
    const res = await bulkUpsertRef("units", rows, true);
    expect(f).toHaveBeenCalledWith(
      "/api/system/refs/units/bulk",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ rows, dry_run: true }) }),
    );
    expect(res).toEqual(plan);
  });

  it("не-200 → null", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await bulkUpsertRef("units", [], false)).toBeNull();
  });

  it("исключение → null", async () => {
    mockFetch(async () => {
      throw new Error("x");
    });
    expect(await bulkUpsertRef("units", [], false)).toBeNull();
  });
});

describe("fetchQualitySummary", () => {
  it("200 → .references из тела", async () => {
    const rows = [{ ref: "core.skus", title: "SKU", total: 10, score: 0.9, issues_count: 1, by_kind: { missing: 1, duplicate: 0, broken_ref: 0, orphan: 0 } }];
    mockFetch(async () => ({ ok: true, json: async () => ({ references: rows }) }));
    expect(await fetchQualitySummary()).toEqual(rows);
  });

  it("URL — /system/references/quality", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => ({ references: [] }) }));
    mockFetch(f);
    await fetchQualitySummary();
    expect(f).toHaveBeenCalledWith(`${BASE}/system/references/quality`, expect.anything());
  });

  it("не-200 → []", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchQualitySummary()).toEqual([]);
  });
});

describe("fetchQualityDetail", () => {
  it("энкодит refKey в URL, возвращает тело", async () => {
    const detail = { ref: "core.skus", title: "SKU", total: 5, score: 1, issues: [] };
    const f = vi.fn(async () => ({ ok: true, json: async () => detail }));
    mockFetch(f);
    const res = await fetchQualityDetail("core skus/x");
    expect(f).toHaveBeenCalledWith(
      `/api/system/references/quality/${encodeURIComponent("core skus/x")}`,
      expect.anything(),
    );
    expect(res).toEqual(detail);
  });

  it("не-200 → null", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchQualityDetail("x")).toBeNull();
  });
});

describe("fetchSimpleRef", () => {
  it("без опций — без query, без заголовков", async () => {
    const rows = [{ code: "PCS", title: "штука", is_active: true }];
    const f = vi.fn(async () => ({ ok: true, json: async () => rows }));
    mockFetch(f);
    const res = await fetchSimpleRef("units");
    expect(f).toHaveBeenCalledWith(`${BASE}/system/refs/units`, expect.objectContaining({ headers: undefined }));
    expect(res).toEqual(rows);
  });

  it("archived=true → ?archived=true в URL, роль в заголовке", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => [] }));
    mockFetch(f);
    await fetchSimpleRef("banks", { archived: true, roles: "admin" });
    expect(f).toHaveBeenCalledWith(
      `${BASE}/system/refs/banks?archived=true`,
      expect.objectContaining({ headers: { "X-User-Roles": "admin" } }),
    );
  });

  it("не-200 → []", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchSimpleRef("currencies")).toEqual([]);
  });
});

describe("fetchRefRowsByEndpoint", () => {
  it("зовёт BASE+endpoint, массив → как есть", async () => {
    const rows = [{ a: 1 }];
    const f = vi.fn(async () => ({ ok: true, json: async () => rows }));
    mockFetch(f);
    const res = await fetchRefRowsByEndpoint("/sales/stages", "rop");
    expect(f).toHaveBeenCalledWith(`${BASE}/sales/stages`, expect.objectContaining({ headers: { "X-User-Roles": "rop" } }));
    expect(res).toEqual(rows);
  });

  it("не массив → []", async () => {
    mockFetch(async () => ({ ok: true, json: async () => ({ not: "array" }) }));
    expect(await fetchRefRowsByEndpoint("/x")).toEqual([]);
  });

  it("не-200 → []", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchRefRowsByEndpoint("/x")).toEqual([]);
  });
});

describe("fetchRefRowsByKey", () => {
  it("POST reference.query с ref=key и лимитом по умолчанию (CATALOG_ROW_LIMIT)", async () => {
    const rows = [{ id: 1 }];
    const f = vi.fn(async () => ({ ok: true, json: async () => ({ result: rows }) }));
    mockFetch(f);
    const res = await fetchRefRowsByKey("core.counterparty", "admin");
    expect(f).toHaveBeenCalledWith(
      `${BASE}/system/references/query`,
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-Roles": "admin" },
        body: JSON.stringify({ ref: "core.counterparty", limit: 250 }),
      }),
    );
    expect(res).toEqual(rows);
  });

  it("не-200 → []", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchRefRowsByKey("x")).toEqual([]);
  });
});

describe("createSimpleRef / patchSimpleRef / archiveSimpleRef", () => {
  it("createSimpleRef → POST /api/system/refs/:table с телом row", async () => {
    const f = vi.fn(async () => ({ ok: true }));
    mockFetch(f);
    const row = { code: "PCS", title: "штука", is_active: true };
    expect(await createSimpleRef("units", row)).toBe(true);
    expect(f).toHaveBeenCalledWith(
      "/api/system/refs/units",
      expect.objectContaining({ method: "POST", body: JSON.stringify(row) }),
    );
  });

  it("createSimpleRef исключение → false", async () => {
    mockFetch(async () => {
      throw new Error("x");
    });
    expect(await createSimpleRef("units", {})).toBe(false);
  });

  it("patchSimpleRef → PATCH /api/system/refs/:table/:code энкодит код", async () => {
    const f = vi.fn(async () => ({ ok: true }));
    mockFetch(f);
    expect(await patchSimpleRef("banks", "AL FA", { title: "Альфа" })).toBe(true);
    expect(f).toHaveBeenCalledWith(
      `/api/system/refs/banks/${encodeURIComponent("AL FA")}`,
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ title: "Альфа" }) }),
    );
  });

  it("patchSimpleRef не ok → false", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await patchSimpleRef("units", "X", {})).toBe(false);
  });

  it("archiveSimpleRef → DELETE /api/system/refs/:table/:code", async () => {
    const f = vi.fn(async () => ({ ok: true }));
    mockFetch(f);
    expect(await archiveSimpleRef("units", "PCS")).toBe(true);
    expect(f).toHaveBeenCalledWith("/api/system/refs/units/PCS", expect.objectContaining({ method: "DELETE" }));
  });

  it("archiveSimpleRef исключение → false", async () => {
    mockFetch(async () => {
      throw new Error("x");
    });
    expect(await archiveSimpleRef("units", "PCS")).toBe(false);
  });
});

describe("fetchCurrencyRates / fetchVatRates", () => {
  it("fetchCurrencyRates без key — без query", async () => {
    const rows = [{ id: 1, currency_code: "USD", rate: 3.2, start_date: "2026-01-01", end_date: null }];
    const f = vi.fn(async () => ({ ok: true, json: async () => rows }));
    mockFetch(f);
    const res = await fetchCurrencyRates();
    expect(f).toHaveBeenCalledWith(`${BASE}/system/refs/currency-rates`, expect.anything());
    expect(res).toEqual(rows);
  });

  it("fetchCurrencyRates с key — ?key=... энкодится", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => [] }));
    mockFetch(f);
    await fetchCurrencyRates("USD/BYN");
    expect(f).toHaveBeenCalledWith(
      `${BASE}/system/refs/currency-rates?key=${encodeURIComponent("USD/BYN")}`,
      expect.anything(),
    );
  });

  it("fetchCurrencyRates не-200 → []", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchCurrencyRates()).toEqual([]);
  });

  it("fetchVatRates с key — ?key=..., URL vat-rates", async () => {
    const rows = [{ id: 1, code: "20", title: "НДС20", rate: 20, start_date: "2026-01-01", end_date: null }];
    const f = vi.fn(async () => ({ ok: true, json: async () => rows }));
    mockFetch(f);
    const res = await fetchVatRates("20", "rop");
    expect(f).toHaveBeenCalledWith(
      `${BASE}/system/refs/vat-rates?key=20`,
      expect.objectContaining({ headers: { "X-User-Roles": "rop" } }),
    );
    expect(res).toEqual(rows);
  });

  it("fetchVatRates не-200 → []", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchVatRates()).toEqual([]);
  });
});

describe("currencyRateAsOf", () => {
  it("энкодит key/on в query, GET /api/system/refs/currency-rates/as-of", async () => {
    const row = { id: 1, currency_code: "USD", rate: 3.2, start_date: "2026-01-01", end_date: null };
    const f = vi.fn(async () => ({ ok: true, json: async () => row }));
    mockFetch(f);
    const res = await currencyRateAsOf("USD/X", "2026-07-01");
    expect(f).toHaveBeenCalledWith(
      `/api/system/refs/currency-rates/as-of?key=${encodeURIComponent("USD/X")}&on=2026-07-01`,
      expect.anything(),
    );
    expect(res).toEqual(row);
  });

  it("не-200 → null", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await currencyRateAsOf("USD", "2026-07-01")).toBeNull();
  });

  it("исключение → null", async () => {
    mockFetch(async () => {
      throw new Error("x");
    });
    expect(await currencyRateAsOf("USD", "2026-07-01")).toBeNull();
  });
});

describe("addRateVersion", () => {
  it("POST /api/system/refs/:table/versions с payload", async () => {
    const f = vi.fn(async () => ({ ok: true }));
    mockFetch(f);
    const payload = { currency_code: "USD", rate: 3.3, start_date: "2026-08-01" };
    expect(await addRateVersion("currency-rates", payload)).toBe(true);
    expect(f).toHaveBeenCalledWith(
      "/api/system/refs/currency-rates/versions",
      expect.objectContaining({ method: "POST", body: JSON.stringify(payload) }),
    );
  });

  it("исключение → false", async () => {
    mockFetch(async () => {
      throw new Error("x");
    });
    expect(await addRateVersion("vat-rates", {})).toBe(false);
  });
});

describe("fetchDuplicateClusters / mergeCounterparties / unmergeCounterparty", () => {
  it("fetchDuplicateClusters → .clusters из тела, URL /system/mdm/duplicates", async () => {
    const clusters = [{ unp: "111", members: [{ id: 1, name: "A" }] }];
    const f = vi.fn(async () => ({ ok: true, json: async () => ({ clusters }) }));
    mockFetch(f);
    const res = await fetchDuplicateClusters();
    expect(f).toHaveBeenCalledWith(`${BASE}/system/mdm/duplicates`, expect.anything());
    expect(res).toEqual(clusters);
  });

  it("fetchDuplicateClusters не-200 → []", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchDuplicateClusters()).toEqual([]);
  });

  it("mergeCounterparties → POST /api/system/mdm/merge с survivor_id/duplicate_id", async () => {
    const f = vi.fn(async () => ({ ok: true }));
    mockFetch(f);
    expect(await mergeCounterparties(1, 2)).toBe(true);
    expect(f).toHaveBeenCalledWith(
      "/api/system/mdm/merge",
      expect.objectContaining({ body: JSON.stringify({ survivor_id: 1, duplicate_id: 2 }) }),
    );
  });

  it("mergeCounterparties исключение → false", async () => {
    mockFetch(async () => {
      throw new Error("x");
    });
    expect(await mergeCounterparties(1, 2)).toBe(false);
  });

  it("unmergeCounterparty → POST /api/system/mdm/unmerge с duplicate_id", async () => {
    const f = vi.fn(async () => ({ ok: true }));
    mockFetch(f);
    expect(await unmergeCounterparty(5)).toBe(true);
    expect(f).toHaveBeenCalledWith(
      "/api/system/mdm/unmerge",
      expect.objectContaining({ body: JSON.stringify({ duplicate_id: 5 }) }),
    );
  });

  it("unmergeCounterparty не ok → false", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await unmergeCounterparty(5)).toBe(false);
  });
});

describe("fetchCounterpartyCard", () => {
  it("GET /system/mdm/counterparty/:id, тело как есть", async () => {
    const card = { id: 1, name: "ООО Ромашка" };
    const f = vi.fn(async () => ({ ok: true, json: async () => card }));
    mockFetch(f);
    const res = await fetchCounterpartyCard(1, "admin");
    expect(f).toHaveBeenCalledWith(
      `${BASE}/system/mdm/counterparty/1`,
      expect.objectContaining({ headers: { "X-User-Roles": "admin" } }),
    );
    expect(res).toEqual(card);
  });

  it("не-200 → null", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchCounterpartyCard(1)).toBeNull();
  });
});

describe("fetchSyncJournal", () => {
  it("GET /integrations/1c/sync-journal, .entries из тела", async () => {
    const entries = [{ id: 1, entity_type: "sku", entity_id: 1, system: "1c", origin: "erp", direction: "out", state: "synced", external_ref: null, last_synced_at: null, error_text: null }];
    const f = vi.fn(async () => ({ ok: true, json: async () => ({ entries }) }));
    mockFetch(f);
    const res = await fetchSyncJournal();
    expect(f).toHaveBeenCalledWith(`${BASE}/integrations/1c/sync-journal`, expect.anything());
    expect(res).toEqual(entries);
  });

  it("не-200 → []", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchSyncJournal()).toEqual([]);
  });
});

describe("fetchSkuCard", () => {
  it("энкодит код в URL, тело как есть", async () => {
    const card = { code: "A1", title: "Реле" };
    const f = vi.fn(async () => ({ ok: true, json: async () => card }));
    mockFetch(f);
    const res = await fetchSkuCard("A 1/x");
    expect(f).toHaveBeenCalledWith(`${BASE}/system/sku/${encodeURIComponent("A 1/x")}`, expect.anything());
    expect(res).toEqual(card);
  });

  it("не-200 → null", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchSkuCard("A1")).toBeNull();
  });
});

describe("fetchSkuLandedInputs", () => {
  it("без on_date — без query", async () => {
    const inputs = { sku_code: "A1", weight_kg: 1 };
    const f = vi.fn(async () => ({ ok: true, json: async () => inputs }));
    mockFetch(f);
    const res = await fetchSkuLandedInputs("A1");
    expect(f).toHaveBeenCalledWith("/api/system/sku/A1/landed-inputs", expect.anything());
    expect(res).toEqual(inputs);
  });

  it("с on_date — ?on_date=... энкодится", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => ({}) }));
    mockFetch(f);
    await fetchSkuLandedInputs("A1", "2026-07-01");
    expect(f).toHaveBeenCalledWith("/api/system/sku/A1/landed-inputs?on_date=2026-07-01", expect.anything());
  });

  it("не-200 → null", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchSkuLandedInputs("A1")).toBeNull();
  });
});

describe("fetchTnvedRates", () => {
  it("энкодит code/on в query", async () => {
    const rates = { code: "8536", name: "Реле", duty_rate: 5, vat_code: "20", vat_rate: 20, excise: null, unit: "шт", as_of: "2026-07-01" };
    const f = vi.fn(async () => ({ ok: true, json: async () => rates }));
    mockFetch(f);
    const res = await fetchTnvedRates("8536 49", "2026-07-01");
    expect(f).toHaveBeenCalledWith(
      `${BASE}/system/tnved/lookup?code=${encodeURIComponent("8536 49")}&on=2026-07-01`,
      expect.anything(),
    );
    expect(res).toEqual(rates);
  });

  it("не-200 → null", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchTnvedRates("8536", "2026-07-01")).toBeNull();
  });
});

describe("fetchSurvivorshipRules", () => {
  it("без entityType — без query; .rules из тела", async () => {
    const rules = [{ id: 1, entity_type: "counterparty", field: "name", strategy: "most_recent", source_priority: [] }];
    const f = vi.fn(async () => ({ ok: true, json: async () => ({ rules }) }));
    mockFetch(f);
    const res = await fetchSurvivorshipRules();
    expect(f).toHaveBeenCalledWith(`${BASE}/system/mdm/rules`, expect.anything());
    expect(res).toEqual(rules);
  });

  it("с entityType — ?entity_type=...", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => ({ rules: [] }) }));
    mockFetch(f);
    await fetchSurvivorshipRules("sku");
    expect(f).toHaveBeenCalledWith(`${BASE}/system/mdm/rules?entity_type=sku`, expect.anything());
  });

  it("не-200 → []", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchSurvivorshipRules()).toEqual([]);
  });
});

describe("fetchNomenclatureGroups", () => {
  it("без опций — без query", async () => {
    const groups = [{ id: 1, code: "CAT-1", name: "Группа", parent_id: null, is_active: true }];
    const f = vi.fn(async () => ({ ok: true, json: async () => groups }));
    mockFetch(f);
    const res = await fetchNomenclatureGroups();
    expect(f).toHaveBeenCalledWith(`${BASE}/system/refs/nomenclature-groups`, expect.objectContaining({ headers: undefined }));
    expect(res).toEqual(groups);
  });

  it("archived=true — ?archived=true", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => [] }));
    mockFetch(f);
    await fetchNomenclatureGroups({ archived: true, roles: "admin" });
    expect(f).toHaveBeenCalledWith(
      `${BASE}/system/refs/nomenclature-groups?archived=true`,
      expect.objectContaining({ headers: { "X-User-Roles": "admin" } }),
    );
  });

  it("не-200 → []", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await fetchNomenclatureGroups()).toEqual([]);
  });
});

describe("createNomenclatureGroup / patchNomenclatureGroup / archiveNomenclatureGroup", () => {
  it("createNomenclatureGroup → POST /api/system/refs/nomenclature-groups с телом группы", async () => {
    const f = vi.fn(async () => ({ ok: true }));
    mockFetch(f);
    const group = { code: "CAT-1", name: "Группа", parent_id: null };
    expect(await createNomenclatureGroup(group)).toBe(true);
    expect(f).toHaveBeenCalledWith(
      "/api/system/refs/nomenclature-groups",
      expect.objectContaining({ method: "POST", body: JSON.stringify(group) }),
    );
  });

  it("createNomenclatureGroup исключение → false", async () => {
    mockFetch(async () => {
      throw new Error("x");
    });
    expect(await createNomenclatureGroup({ code: "X", name: "Y" })).toBe(false);
  });

  it("patchNomenclatureGroup → PATCH энкодит код, тело — поля", async () => {
    const f = vi.fn(async () => ({ ok: true }));
    mockFetch(f);
    const fields = { name: "Новое имя", parent_id: 2 };
    expect(await patchNomenclatureGroup("CAT 1", fields)).toBe(true);
    expect(f).toHaveBeenCalledWith(
      `/api/system/refs/nomenclature-groups/${encodeURIComponent("CAT 1")}`,
      expect.objectContaining({ method: "PATCH", body: JSON.stringify(fields) }),
    );
  });

  it("patchNomenclatureGroup не ok → false", async () => {
    mockFetch(async () => ({ ok: false }));
    expect(await patchNomenclatureGroup("CAT-1", {})).toBe(false);
  });

  it("archiveNomenclatureGroup → DELETE энкодит код", async () => {
    const f = vi.fn(async () => ({ ok: true }));
    mockFetch(f);
    expect(await archiveNomenclatureGroup("CAT 1")).toBe(true);
    expect(f).toHaveBeenCalledWith(
      `/api/system/refs/nomenclature-groups/${encodeURIComponent("CAT 1")}`,
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("archiveNomenclatureGroup исключение → false", async () => {
    mockFetch(async () => {
      throw new Error("x");
    });
    expect(await archiveNomenclatureGroup("CAT-1")).toBe(false);
  });
});
