import { beforeEach, describe, expect, it, vi } from "vitest";

const json = vi.hoisted(() => vi.fn());

vi.mock("next/headers", () => ({ cookies: vi.fn() }));
vi.mock("@/lib/access", () => ({ ROLE_COOKIE: "aios_role", USER_COOKIE: "aios_user" }));
vi.mock("@/lib/auth-mode", () => ({ frontendAuthMode: () => "oidc" }));

import { POST } from "./route";

describe("POST /api/auth/login", () => {
  beforeEach(() => json.mockClear());

  it("does not expose picker-based dev login when OIDC is enabled", async () => {
    const response = await POST({ json } as unknown as Request);

    expect(response.status).toBe(403);
    await expect(response.json()).resolves.toEqual({ error: "Используйте корпоративный вход" });
    expect(json).not.toHaveBeenCalled();
  });
});
