import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  jar: { get: vi.fn(), set: vi.fn() },
  config: null as null | { issuer: string; clientId: string },
}));

vi.mock("next/headers", () => ({ cookies: vi.fn(async () => state.jar) }));
vi.mock("@/lib/auth-mode", () => ({ keycloakPublicConfig: () => state.config }));
vi.mock("@/lib/keycloak-token", () => ({
  REFRESH_COOKIE: "aios_refresh_token",
  accessTokenNeedsRefresh: vi.fn(),
  refreshAccessToken: vi.fn(),
}));
vi.mock("@/lib/oidc-cookies", () => ({ applyOidcTokenCookies: vi.fn() }));

import { ensureFreshAccessToken } from "@/lib/auth-session-server";
import * as keycloak from "@/lib/keycloak-token";
import * as oidcCookies from "@/lib/oidc-cookies";

beforeEach(() => {
  vi.clearAllMocks();
  state.config = null;
  state.jar.get.mockImplementation((name: string) =>
    name === "aios_access_token" ? { value: "access" } : undefined,
  );
  (keycloak.accessTokenNeedsRefresh as ReturnType<typeof vi.fn>).mockReturnValue(false);
});

describe("auth-session-server", () => {
  it("возвращает действующий токен и не обновляет без refresh/config", async () => {
    await expect(ensureFreshAccessToken()).resolves.toBe("access");
    (keycloak.accessTokenNeedsRefresh as ReturnType<typeof vi.fn>).mockReturnValue(true);
    await expect(ensureFreshAccessToken()).resolves.toBe("access");
    state.jar.get.mockImplementation((name: string) =>
      name === "aios_access_token" ? { value: "access" } : name === "aios_refresh_token" ? { value: "refresh" } : undefined,
    );
    await expect(ensureFreshAccessToken()).resolves.toBe("access");
  });

  it("обновляет токен и применяет обе cookie, а неуспешный refresh сохраняет старый", async () => {
    (keycloak.accessTokenNeedsRefresh as ReturnType<typeof vi.fn>).mockReturnValue(true);
    state.jar.get.mockImplementation((name: string) =>
      name === "aios_access_token" ? { value: "old" } : name === "aios_refresh_token" ? { value: "refresh" } : undefined,
    );
    state.config = { issuer: "https://issuer", clientId: "crm" };
    (keycloak.refreshAccessToken as ReturnType<typeof vi.fn>).mockResolvedValue({ access_token: "new", refresh_token: "next" });
    await expect(ensureFreshAccessToken()).resolves.toBe("new");
    expect(oidcCookies.applyOidcTokenCookies).toHaveBeenCalled();
    (keycloak.refreshAccessToken as ReturnType<typeof vi.fn>).mockResolvedValue(null);
    await expect(ensureFreshAccessToken()).resolves.toBe("old");
  });
});
