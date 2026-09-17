import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ mode: "dev" as "dev" | "oidc" }));
const jar = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("next/headers", () => ({ cookies: vi.fn(async () => jar) }));
vi.mock("@/lib/auth-mode", () => ({
  frontendAuthMode: () => auth.mode,
  keycloakPublicConfig: () => null,
}));

import {
  backendAuthHeaders,
  currentAccessToken as currentBackendToken,
} from "@/lib/auth-headers-server";
import {
  currentAccessToken as currentRoleToken,
  currentRole,
  currentUserName,
} from "@/lib/role-server";

beforeEach(() => {
  vi.clearAllMocks();
  auth.mode = "dev";
  const values: Record<string, string | undefined> = {};
  jar.get.mockImplementation((name: string) =>
    values[name] == null ? undefined : { value: values[name] },
  );
  (jar as typeof jar & { values?: typeof values }).values = values;
});

function setCookies(values: Record<string, string | undefined>) {
  jar.get.mockImplementation((name: string) =>
    values[name] == null ? undefined : { value: values[name] },
  );
}

describe("server auth helpers", () => {
  it("строит dev-заголовки с ролью и bearer, а без cookie использует director", async () => {
    setCookies({ aios_role: "sales", aios_access_token: "secret" });
    await expect(backendAuthHeaders()).resolves.toEqual({
      Authorization: "Bearer secret",
      "X-User-Roles": "sales",
    });
    setCookies({});
    await expect(backendAuthHeaders()).resolves.toEqual({ "X-User-Roles": "director" });
  });

  it("учитывает override и oidc-режим, не теряя диагностическую роль", async () => {
    auth.mode = "oidc";
    setCookies({ aios_role: "viewer", aios_access_token: "token" });
    await expect(backendAuthHeaders("director")).resolves.toEqual({
      Authorization: "Bearer token",
      "X-User-Roles": "director",
    });
    setCookies({ aios_role: "viewer" });
    await expect(backendAuthHeaders()).resolves.toEqual({ "X-User-Roles": "viewer" });
  });

  it("читает текущую роль, access token и URL-кодированное имя", async () => {
    setCookies({ aios_role: "sales", aios_access_token: "t", aios_user: "%D0%98%D0%B2%D0%B0%D0%BD" });
    await expect(currentRole()).resolves.toBe("sales");
    await expect(currentBackendToken()).resolves.toBe("t");
    await expect(currentRoleToken()).resolves.toBe("t");
    await expect(currentUserName()).resolves.toBe("Иван");
    setCookies({ aios_user: "%E0%A4%A" });
    await expect(currentUserName()).resolves.toBe("%E0%A4%A");
    setCookies({});
    await expect(currentUserName()).resolves.toBeNull();
  });
});
