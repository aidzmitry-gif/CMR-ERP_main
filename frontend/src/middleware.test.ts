// @vitest-environment node

import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/auth-mode", () => ({
  frontendAuthMode: () => "oidc",
  keycloakPublicConfig: () => ({ issuer: "https://auth.belakb.by/realms/aios", clientId: "aios-backend" }),
}));
vi.mock("@/lib/keycloak-token", () => ({
  REFRESH_COOKIE: "aios_refresh_token",
  accessTokenNeedsRefresh: (token: string | undefined) => token !== "fresh-token",
  refreshAccessToken: vi.fn(),
  rolesFromAccessToken: vi.fn(() => ["sales"]),
}));
vi.mock("@/lib/oidc-cookies", () => ({
  applyOidcTokenCookies: (
    tokens: { access_token: string },
    set: (name: string, value: string, opts: { path: string }) => void,
  ) => set("aios_access_token", tokens.access_token, { path: "/" }),
}));

import { refreshAccessToken, rolesFromAccessToken } from "@/lib/keycloak-token";
import { middleware } from "@/middleware";

function request(path: string, cookies: Record<string, string> = {}) {
  const cookie = Object.entries(cookies)
    .map(([name, value]) => `${name}=${value}`)
    .join("; ");
  return new NextRequest(`https://erp.belakb.by${path}`, {
    headers: cookie ? { cookie, "x-request-id": "request-1" } : { "x-request-id": "request-1" },
  });
}

describe("OIDC middleware session guard", () => {
  beforeEach(() => {
    vi.mocked(refreshAccessToken).mockReset();
    vi.mocked(rolesFromAccessToken).mockReturnValue(["sales"]);
  });

  it.each([undefined, "expired-token"])("redirects protected routes when access token is %s", async (access) => {
    const req = request("/erp", access ? { aios_access_token: access } : {});

    const res = await middleware(req);

    expect(res.headers.get("location")).toBe("https://erp.belakb.by/login?error=session_expired");
  });

  it("forwards a refreshed token in the current request and persists it in the response", async () => {
    vi.mocked(refreshAccessToken).mockResolvedValue({ access_token: "fresh-token", expires_in: 300 });
    const req = request("/erp", {
      aios_access_token: "expired-token",
      aios_refresh_token: "refresh-token",
    });

    const res = await middleware(req);

    expect(req.cookies.get("aios_access_token")?.value).toBe("fresh-token");
    expect(res.cookies.get("aios_access_token")?.value).toBe("fresh-token");
    expect(res.headers.get("x-middleware-request-cookie")).toContain("aios_access_token=fresh-token");
    expect(res.headers.get("x-middleware-request-x-request-id")).toBe("request-1");
    expect(refreshAccessToken).toHaveBeenCalledWith({
      issuer: "https://auth.belakb.by/realms/aios",
      clientId: "aios-backend",
      refreshToken: "refresh-token",
    });
  });

  it("keeps rotated cookies when a refreshed onboarding user is redirected", async () => {
    vi.mocked(refreshAccessToken).mockResolvedValue({ access_token: "fresh-token" });
    vi.mocked(rolesFromAccessToken).mockReturnValue(["onboarding"]);
    const res = await middleware(request("/erp", {
      aios_access_token: "expired-token", aios_refresh_token: "refresh-token",
    }));
    expect(res.headers.get("location")).toBe("https://erp.belakb.by/onboarding");
    expect(res.cookies.get("aios_access_token")?.value).toBe("fresh-token");
  });
});
