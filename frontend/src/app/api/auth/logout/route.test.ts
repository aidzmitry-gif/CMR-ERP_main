import { beforeEach, describe, expect, it, vi } from "vitest";

const { removeCookie, config } = vi.hoisted(() => ({
  removeCookie: vi.fn(),
  config: vi.fn(),
}));

vi.mock("next/headers", () => ({ cookies: async () => ({ delete: removeCookie }) }));
vi.mock("@/lib/auth-mode", () => ({ keycloakPublicConfig: config }));

import { POST } from "./route";

describe("POST /api/auth/logout", () => {
  beforeEach(() => {
    removeCookie.mockClear();
    config.mockReturnValue({ issuer: "https://auth.example.test/realms/erp", clientId: "erp" });
    vi.stubEnv("NEXT_PUBLIC_APP_ORIGIN", "https://erp.example.test");
  });

  it("ends local login and navigates the browser to Keycloak instead of silently signing in again", async () => {
    const response = await POST(new Request("http://localhost:3100/api/auth/logout", { method: "POST" }));
    expect(response.status).toBe(303);
    expect(response.headers.get("Location")).toBe("https://auth.example.test/realms/erp/protocol/openid-connect/logout");
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    for (const cookie of ["aios_role", "aios_user", "aios_access_token", "aios_refresh_token", "aios_oidc_state", "aios_oidc_verifier"]) {
      expect(removeCookie).toHaveBeenCalledWith(cookie);
    }
  });

  it("keeps local development logout on the public login page without Keycloak configuration", async () => {
    config.mockReturnValue(null);
    const response = await POST(new Request("http://localhost:3100/api/auth/logout", { method: "POST" }));
    expect(response.status).toBe(303);
    expect(response.headers.get("Location")).toBe("https://erp.example.test/login");
  });
});
