import { afterEach, describe, expect, it, vi } from "vitest";
import * as inventory from "@/lib/wms-inventory";
import { createCyclePlan, fetchCyclePlans, fetchCyclePlansServer, runCyclePlan } from "@/lib/wms-cycle-count";
import { confirmation, detail, inventory as count, jsonResponse, organizations, plan } from "@/test/inventory-fixtures";

afterEach(() => vi.unstubAllGlobals());
const auth = { Authorization: "Bearer synthetic-token", "X-User-Roles": "warehouse", "X-User": "operator" };

it("статусы и тон сохраняют исходные сценарии", () => {
  expect(["open", "done", "canceled"].map((s) => inventory.inventoryStatusLabel(s as inventory.InventoryStatus))).toEqual(["Идёт пересчёт", "Проведена", "Отменена"]);
  expect(inventory.inventoryStatusLabel("unknown" as inventory.InventoryStatus)).toBe("unknown");
  expect([null, 0, -1, 1].map(inventory.varianceTone)).toEqual(["none", "ok", "short", "over"]);
});

it("SSR передаёт реальные auth headers и org фильтр без подмены ролью", async () => {
  const fetcher = vi.fn().mockResolvedValue(jsonResponse([])); vi.stubGlobal("fetch", fetcher);
  await inventory.fetchInventoryListServer(auth, 2);
  expect(fetcher).toHaveBeenLastCalledWith("http://127.0.0.1:8000/wms/inventory?organization_id=2", { cache: "no-store", headers: auth });
  fetcher.mockResolvedValue(jsonResponse(plan())); await fetchCyclePlansServer(auth, 2);
  expect(fetcher).toHaveBeenLastCalledWith("http://127.0.0.1:8000/wms/cycle-plans?organization_id=2", { cache: "no-store", headers: auth });
  fetcher.mockResolvedValue(jsonResponse(detail())); await inventory.fetchInventoryDetailServer("7", auth);
  expect(fetcher).toHaveBeenLastCalledWith("http://127.0.0.1:8000/wms/inventory/7", { cache: "no-store", headers: auth });
  fetcher.mockResolvedValue(jsonResponse(organizations)); await inventory.fetchInventoryOrganizationsServer(auth);
  expect(fetcher).toHaveBeenLastCalledWith("http://127.0.0.1:8000/wms/receipt-organizations", { cache: "no-store", headers: auth });
});

it("создание и run передают явные org/source/evidence/confirmation", async () => {
  const fetcher = vi.fn().mockResolvedValue(jsonResponse(count())); vi.stubGlobal("fetch", fetcher);
  const input = { organization_id: 2, warehouse: "Склад", ...confirmation };
  await inventory.createInventory(input);
  expect(fetcher).toHaveBeenLastCalledWith("/api/wms/inventory", inventory.inventoryJson("POST", input));
  fetcher.mockResolvedValue(jsonResponse(plan()));
  await createCyclePlan({ ...input, cadence_days: 7, next_due_date: "2026-09-09" });
  expect(JSON.parse(fetcher.mock.calls.at(-1)![1].body)).toEqual({ ...input, cadence_days: 7, next_due_date: "2026-09-09" });
  fetcher.mockResolvedValue(jsonResponse(detail())); await runCyclePlan(3, confirmation);
  expect(fetcher).toHaveBeenLastCalledWith("/api/wms/cycle-plans/3/run", inventory.inventoryJson("POST", confirmation));
});

it("клиентские списки фильтруют org, операции сохраняют количество и null стоимости", async () => {
  const fetcher = vi.fn().mockResolvedValue(jsonResponse([])); vi.stubGlobal("fetch", fetcher);
  await inventory.fetchInventoryList(2); expect(fetcher.mock.calls.at(-1)![0]).toBe("/api/wms/inventory?organization_id=2");
  fetcher.mockResolvedValue(jsonResponse([])); await fetchCyclePlans(2); expect(fetcher.mock.calls.at(-1)![0]).toBe("/api/wms/cycle-plans?organization_id=2");
  fetcher.mockResolvedValue(jsonResponse(detail())); expect((await inventory.populateInventory(7)).summary.net_value).toBeNull();
  fetcher.mockResolvedValue(jsonResponse(detail().lines[0])); await inventory.updateInventoryLine(10, { counted_qty: 0 });
  expect(fetcher).toHaveBeenLastCalledWith("/api/wms/inventory/lines/10", inventory.inventoryJson("PATCH", { counted_qty: 0 }));
  fetcher.mockResolvedValue(jsonResponse(detail().lines[0])); await inventory.addInventoryLine(7, "SKU", 1.25);
  expect(fetcher).toHaveBeenLastCalledWith("/api/wms/inventory/7/lines", inventory.inventoryJson("POST", { sku_code: "SKU", counted_qty: 1.25 }));
});

const calls = [
  () => inventory.fetchInventoryListServer(auth, 1), () => inventory.fetchInventoryDetailServer("7", auth),
  () => inventory.fetchInventoryOrganizationsServer(auth), () => inventory.fetchInventoryList(1),
  () => inventory.createInventory({ organization_id: 1, warehouse: "W", ...confirmation }),
  () => inventory.fetchInventoryDetail(7), () => inventory.populateInventory(7),
  () => inventory.updateInventoryLine(10, { counted_qty: 1 }), () => inventory.addInventoryLine(7, "SKU"), () => inventory.completeInventory(7),
  () => fetchCyclePlansServer(auth, 1), () => fetchCyclePlans(1),
  () => createCyclePlan({ organization_id: 1, warehouse: "W", cadence_days: 7, next_due_date: "2026-09-09", ...confirmation }),
  () => runCyclePlan(3, confirmation),
];
describe.each([403, 404, 409, 503])("HTTP %s не превращается в []/null/false", (status) => {
  it("каждый endpoint сохраняет ошибку и статус", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse({ detail: "synthetic detail" }, status))));
    for (const call of calls) await expect(call()).rejects.toMatchObject({ status, message: expect.stringContaining("synthetic detail") });
  });
});
it("каждый endpoint честно сообщает сетевой сбой", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
  for (const call of calls) await expect(call()).rejects.toThrow("Ошибка сети");
});
it("некорректный JSON не становится пустым успехом", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not-json", { status: 200 })));
  await expect(inventory.fetchInventoryList(1)).rejects.toThrow("некорректный ответ");
});
