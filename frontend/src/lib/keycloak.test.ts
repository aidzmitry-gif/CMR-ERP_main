import { afterEach, describe, expect, it, vi } from "vitest";

import {
  authorizeUrl,
  exchangeCode,
  pkceChallenge,
  randomUrlSafe,
  resolveKeycloakConfig,
} from "@/lib/keycloak";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("keycloak helpers", () => {
  it("генерирует URL-safe nonce и воспроизводимый PKCE challenge", () => {
    const nonce = randomUrlSafe(24);
    expect(nonce).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(nonce).toHaveLength(32);
    expect(pkceChallenge("verifier")).toBe(pkceChallenge("verifier"));
    expect(pkceChallenge("verifier")).not.toBe(pkceChallenge("another-verifier"));
  });

  it("строит callback config из окружения или origin запроса", () => {
    vi.stubEnv("NEXT_PUBLIC_KEYCLOAK_ISSUER", "https://sso.example/realms/erp/");
    vi.stubEnv("NEXT_PUBLIC_KEYCLOAK_CLIENT_ID", "erp-web");
    vi.stubEnv("NEXT_PUBLIC_APP_ORIGIN", "");
    expect(resolveKeycloakConfig("https://crm.example/api/auth/oidc/start")).toEqual({
      issuer: "https://sso.example/realms/erp",
      clientId: "erp-web",
      redirectUri: "https://crm.example/api/auth/oidc/callback",
    });

    vi.stubEnv("NEXT_PUBLIC_APP_ORIGIN", "https://erp.example/");
    expect(resolveKeycloakConfig("https://crm.example/api/auth/oidc/start")?.redirectUri).toBe(
      "https://erp.example/api/auth/oidc/callback",
    );

    vi.stubEnv("NEXT_PUBLIC_KEYCLOAK_ISSUER", "");
    expect(resolveKeycloakConfig("https://crm.example/api/auth/oidc/start")).toBeNull();
  });

  it("собирает authorize URL с PKCE параметрами", () => {
    const url = new URL(
      authorizeUrl({
        issuer: "https://sso.example/realms/erp",
        clientId: "erp-web",
        redirectUri: "https://crm.example/callback",
        state: "state-1",
        challenge: "challenge-1",
      }),
    );
    expect(url.pathname).toContain("/protocol/openid-connect/auth");
    expect(url.searchParams.get("client_id")).toBe("erp-web");
    expect(url.searchParams.get("redirect_uri")).toBe("https://crm.example/callback");
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
  });

  it("обменивает code, а при HTTP/сетевой ошибке возвращает null", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ access_token: "access", refresh_token: "refresh" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(new Response("bad gateway", { status: 502 }))
      .mockRejectedValueOnce(new Error("network"));
    vi.stubGlobal("fetch", fetchMock);

    const opts = {
      issuer: "https://sso.example/realms/erp/",
      clientId: "erp-web",
      redirectUri: "https://crm.example/callback",
      code: "abc",
      verifier: "verifier",
    };
    expect((await exchangeCode(opts))?.access_token).toBe("access");
    expect(await exchangeCode(opts)).toBeNull();
    expect(await exchangeCode(opts)).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      "https://sso.example/realms/erp/protocol/openid-connect/token",
      expect.objectContaining({ method: "POST", cache: "no-store" }),
    );
  });
});
