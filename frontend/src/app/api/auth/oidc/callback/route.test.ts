import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const jar = vi.hoisted(() => ({
  get: vi.fn(),
  delete: vi.fn(),
  set: vi.fn(),
}));
const kc = vi.hoisted(() => ({
  OIDC_STATE_COOKIE: "aios_oidc_state",
  OIDC_VERIFIER_COOKIE: "aios_oidc_verifier",
  REFRESH_COOKIE: "aios_refresh_token",
  displayNameFromAccessToken: vi.fn(() => "Иван Иванов"),
  exchangeCode: vi.fn(),
  resolveKeycloakConfig: vi.fn(),
  rolesFromAccessToken: vi.fn(() => ["admin"]),
}));

vi.mock("next/headers", () => ({ cookies: vi.fn(async () => jar) }));
vi.mock("@/lib/keycloak", () => kc);

import { GET } from "@/app/api/auth/oidc/callback/route";

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv("NEXT_PUBLIC_APP_ORIGIN", "https://crm.example/");
  kc.resolveKeycloakConfig.mockReturnValue({
    issuer: "https://sso.example/realms/erp",
    clientId: "erp-web",
    redirectUri: "https://crm.example/api/auth/oidc/callback",
  });
  kc.exchangeCode.mockResolvedValue({ access_token: "access", refresh_token: "refresh", expires_in: 120 });
  jar.get.mockImplementation((name: string) => {
    if (name === "aios_oidc_state") return { value: "state-ok" };
    if (name === "aios_oidc_verifier") return { value: "verifier-ok" };
    return undefined;
  });
});

function req(query: string): NextRequest {
  return new NextRequest(`https://frontend.example/api/auth/oidc/callback?${query}`);
}

describe("GET /api/auth/oidc/callback", () => {
  it("возвращает ошибки callback на login до обращения к token endpoint", async () => {
    expect((await GET(req("error=access_denied"))).headers.get("location")).toContain(
      "/login?error=access_denied",
    );
    expect((await GET(req("code=only"))).headers.get("location")).toContain("missing_code");

    kc.resolveKeycloakConfig.mockReturnValueOnce(null);
    expect((await GET(req("code=abc&state=state-ok"))).headers.get("location")).toContain(
      "kc_unconfigured",
    );
  });

  it("проверяет state/verifier и честно сообщает об ошибке обмена code", async () => {
    jar.get.mockImplementation((name: string) => {
      if (name === "aios_oidc_state") return { value: "other-state" };
      if (name === "aios_oidc_verifier") return { value: "verifier-ok" };
      return undefined;
    });
    expect((await GET(req("code=abc&state=state-ok"))).headers.get("location")).toContain(
      "state_mismatch",
    );

    jar.get.mockImplementation((name: string) => {
      if (name === "aios_oidc_state") return { value: "state-ok" };
      if (name === "aios_oidc_verifier") return { value: "verifier-ok" };
      return undefined;
    });
    kc.exchangeCode.mockResolvedValueOnce(null);
    expect((await GET(req("code=abc&state=state-ok"))).headers.get("location")).toContain(
      "token_exchange",
    );
    expect(jar.delete).toHaveBeenCalledWith("aios_oidc_state");
    expect(jar.delete).toHaveBeenCalledWith("aios_oidc_verifier");
  });

  it("ставит access/refresh/role/user cookies и ведёт admin на CRM", async () => {
    const res = await GET(req("code=abc&state=state-ok"));
    expect(res.headers.get("location")).toBe("https://crm.example/crm/deals");
    expect(kc.exchangeCode).toHaveBeenCalledWith(
      expect.objectContaining({ code: "abc", verifier: "verifier-ok" }),
    );
    expect(jar.set).toHaveBeenCalledWith("aios_access_token", "access", expect.objectContaining({ maxAge: 120 }));
    expect(jar.set).toHaveBeenCalledWith("aios_refresh_token", "refresh", expect.any(Object));
    expect(jar.set).toHaveBeenCalledWith("aios_role", "admin", expect.any(Object));
    expect(jar.set).toHaveBeenCalledWith("aios_user", "Иван Иванов", expect.any(Object));
  });
});
