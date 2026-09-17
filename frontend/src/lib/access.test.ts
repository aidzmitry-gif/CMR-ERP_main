import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchAccess, fetchUsers, slugsForRole, type AccessData } from "@/lib/access";

afterEach(() => vi.unstubAllGlobals());

describe("access API", () => {
  it("читает список пользователей и безопасно возвращает пустой список при сбое", async () => {
    const users = [{ username: "ivan", full_name: "Иван", role: "sales", role_title: "Продажи" }];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ users }) }));
    await expect(fetchUsers()).resolves.toEqual(users);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
    await expect(fetchUsers()).resolves.toEqual([]);
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    await expect(fetchUsers()).resolves.toEqual([]);
  });

  it("передаёт роль и дополнительные заголовки в матрицу доступа", async () => {
    const data: AccessData = { matrix: { sales: ["deals"] }, roles: [], current_roles: ["sales"] };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => data });
    vi.stubGlobal("fetch", fetchMock);
    await expect(fetchAccess("sales", { Authorization: "Bearer t" })).resolves.toEqual(data);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/system/access"),
      expect.objectContaining({ headers: { "X-User-Roles": "sales", Authorization: "Bearer t" } }),
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
    await expect(fetchAccess("sales")).resolves.toBeNull();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    await expect(fetchAccess("sales")).resolves.toBeNull();
    expect(slugsForRole(data, "sales")).toEqual(["deals"]);
    expect(slugsForRole(data, "unknown")).toEqual([]);
  });
});
