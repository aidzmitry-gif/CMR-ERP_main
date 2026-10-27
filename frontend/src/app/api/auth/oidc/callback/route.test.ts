import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { exchange, jar } = vi.hoisted(() => ({
  exchange: vi.fn(),
  jar: { get: vi.fn(), set: vi.fn(), delete: vi.fn() },
}));

vi.mock("next/headers", () => ({ cookies: async () => jar }));
vi.mock("@/lib/keycloak", async (original) => ({
  ...await original<typeof import("@/lib/keycloak")>(),
  exchangeCode: exchange,
  rolesFromAccessToken: () => ["director"],
  displayNameFromAccessToken: () => "Test director",
}));

import { GET } from "./route";

describe("OIDC callback runtime origin", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubEnv("AIOS_OIDC_APP_ORIGIN", "http://127.0.0.1:3100");
    vi.stubEnv("NEXT_PUBLIC_APP_ORIGIN", "https://belakb.by");
    vi.stubEnv("NEXT_PUBLIC_KEYCLOAK_ISSUER", "https://auth.belakb.by/realms/aios");
    vi.stubEnv("NEXT_PUBLIC_KEYCLOAK_CLIENT_ID", "aios-backend");
    jar.get.mockImplementation((name: string) => ({
      value: name === "aios_oidc_state" ? "fixture-state" : "fixture-verifier",
    }));
    exchange.mockResolvedValue({ access_token: "fixture-access-token", expires_in: 300 });
  });
  afterEach(() => vi.unstubAllEnvs());

  it("exchanges the code for the runtime callback and returns to the same instance", async () => {
    const response = await GET(new NextRequest(
      "http://127.0.0.1:3100/api/auth/oidc/callback?code=fixture-code&state=fixture-state",
    ));
    expect(exchange).toHaveBeenCalledWith(expect.objectContaining({
      redirectUri: "http://127.0.0.1:3100/api/auth/oidc/callback",
    }));
    expect(new URL(response.headers.get("Location")!).origin).toBe("http://127.0.0.1:3100");
    expect(jar.set).toHaveBeenCalledWith("aios_access_token", "fixture-access-token",
      expect.objectContaining({ httpOnly: true }));
  });

  it("returns callback errors to the runtime instance without exchanging a code", async () => {
    const response = await GET(new NextRequest("http://127.0.0.1:3100/api/auth/oidc/callback"));
    expect(response.headers.get("Location"))
      .toBe("http://127.0.0.1:3100/login?error=missing_code");
    expect(exchange).not.toHaveBeenCalled();
  });
});
