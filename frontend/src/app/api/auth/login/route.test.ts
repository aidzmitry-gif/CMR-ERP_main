import { beforeEach, describe, expect, it, vi } from "vitest";

const { json, mode, setCookie } = vi.hoisted(() => ({ json: vi.fn(), mode: vi.fn(), setCookie: vi.fn() }));

vi.mock("next/headers", () => ({ cookies: async () => ({ set: setCookie }) }));
vi.mock("@/lib/auth-mode", () => ({ frontendAuthMode: mode }));

import { POST } from "./route";

describe("POST /api/auth/login", () => {
  beforeEach(() => { vi.unstubAllGlobals(); json.mockClear(); setCookie.mockClear(); mode.mockReturnValue("oidc"); });

  it("stores the selected dev username separately from its display name", async () => {
    mode.mockReturnValue("dev");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ users: [{ username: "manager", full_name: "Менеджер", role: "sales" }] })));
    const response = await POST(new Request("http://localhost/api/auth/login", {
      method: "POST", body: JSON.stringify({ username: "manager" }),
    }));
    expect(response.status).toBe(200);
    expect(setCookie).toHaveBeenCalledWith("aios_username", "manager", expect.objectContaining({ httpOnly: true }));
    expect(setCookie).toHaveBeenCalledWith("aios_user", "Менеджер", expect.anything());
  });

  it("does not expose picker-based dev login when OIDC is enabled", async () => {
    const response = await POST({ json } as unknown as Request);

    expect(response.status).toBe(403);
    await expect(response.json()).resolves.toEqual({ error: "Используйте корпоративный вход" });
    expect(json).not.toHaveBeenCalled();
  });
});
