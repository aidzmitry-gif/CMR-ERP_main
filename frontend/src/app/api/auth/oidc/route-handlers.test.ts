import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const jar = vi.hoisted(() => ({
  set: vi.fn(),
  delete: vi.fn(),
}));
const kc = vi.hoisted(() => ({
  OIDC_STATE_COOKIE: "aios_oidc_state",
  OIDC_VERIFIER_COOKIE: "aios_oidc_verifier",
  REFRESH_COOKIE: "aios_refresh_token",
  authorizeUrl: vi.fn(() => "https://sso.example/auth?client_id=erp-web"),
  pkceChallenge: vi.fn(() => "challenge"),
  randomUrlSafe: vi.fn((bytes: number) => (bytes === 32 ? "verifier" : "state")),
  resolveKeycloakConfig: vi.fn(),
}));
const auth = vi.hoisted(() => ({ ensureFreshAccessToken: vi.fn() }));

vi.mock("next/headers", () => ({ cookies: vi.fn(async () => jar) }));
vi.mock("@/lib/keycloak", () => kc);
vi.mock("@/lib/auth-session-server", () => auth);

import { POST as logout } from "@/app/api/auth/logout/route";
import { POST as refresh } from "@/app/api/auth/oidc/refresh/route";
import { GET as start } from "@/app/api/auth/oidc/start/route";

beforeEach(() => {
  vi.clearAllMocks();
  kc.resolveKeycloakConfig.mockReturnValue({
    issuer: "https://sso.example/realms/erp",
    clientId: "erp-web",
    redirectUri: "https://crm.example/api/auth/oidc/callback",
  });
  auth.ensureFreshAccessToken.mockResolvedValue(null);
});

describe("OIDC auxiliary routes", () => {
  it("logout удаляет все session cookies", async () => {
    const res = await logout();
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
    expect(jar.delete).toHaveBeenCalledTimes(4);
  });

  it("start сообщает о ненастроенном Keycloak и сохраняет PKCE state при настройке", async () => {
    kc.resolveKeycloakConfig.mockReturnValueOnce(null);
    expect((await start(new NextRequest("https://crm.example/api/auth/oidc/start"))).status).toBe(503);

    const res = await start(new NextRequest("https://crm.example/api/auth/oidc/start"));
    expect(res.headers.get("location")).toBe("https://sso.example/auth?client_id=erp-web");
    expect(jar.set).toHaveBeenCalledWith("aios_oidc_verifier", "verifier", expect.any(Object));
    expect(jar.set).toHaveBeenCalledWith("aios_oidc_state", "state", expect.any(Object));
    expect(kc.pkceChallenge).toHaveBeenCalledWith("verifier");
  });

  it("refresh различает отсутствие сессии и успешный access token", async () => {
    expect((await refresh()).status).toBe(401);
    auth.ensureFreshAccessToken.mockResolvedValueOnce("access");
    const res = await refresh();
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
  });
});
