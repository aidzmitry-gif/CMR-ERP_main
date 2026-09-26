import { afterEach, expect, it, vi } from "vitest";

import { searchAccountingEmployees } from "@/lib/accounting-employees";

afterEach(() => vi.unstubAllGlobals());

const employee = {
  employee: "Тестовый сотрудник", employee_id: "17", employment_binding_id: "61",
  employee_contract_ref: "ТРУД-17", employee_binding_revision: "2",
  employee_binding_digest: "a".repeat(64), department: "Производство",
};

it("queries the selected organization's employment snapshots privately by date", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({
    organization_id: 7, on: "2026-09-01", items: [employee],
  }) });
  vi.stubGlobal("fetch", fetcher);
  expect(await searchAccountingEmployees("7", "2026-09-01", " Тестовый ")).toEqual([employee]);
  expect(fetcher.mock.calls[0][0]).toBe(
    "/api/accounting/organizations/7/manual-employees?on=2026-09-01&q=%D0%A2%D0%B5%D1%81%D1%82%D0%BE%D0%B2%D1%8B%D0%B9",
  );
  expect(fetcher.mock.calls[0][1]).toEqual({ cache: "no-store" });
  expect(await searchAccountingEmployees("7", "2026-09-01", " ")).toEqual([]);
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("rejects employee snapshots returned for another organization or date", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({
    organization_id: 8, on: "2026-09-01", items: [employee],
  }) });
  vi.stubGlobal("fetch", fetcher);
  await expect(searchAccountingEmployees("7", "2026-09-01", "Тестовый"))
    .rejects.toThrow("другой организации или даты");
});

it("rejects malformed or oversized employment snapshots", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({
    organization_id: 7, on: "2026-09-01", items: [{ ...employee, employee_id: 17 }],
  }) });
  vi.stubGlobal("fetch", fetcher);
  await expect(searchAccountingEmployees("7", "2026-09-01", "Тестовый"))
    .rejects.toThrow("некорректные записи");
  fetcher.mockResolvedValue({ ok: true, json: async () => ({
    organization_id: 7, on: "2026-09-01", items: Array(51).fill(employee),
  }) });
  await expect(searchAccountingEmployees("7", "2026-09-01", "Тестовый"))
    .rejects.toThrow("некорректные записи");
});
