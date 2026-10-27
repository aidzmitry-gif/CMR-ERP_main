import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { oidcAppOrigin, resolveKeycloakConfig } from "@/lib/keycloak";

describe("server OIDC origin", () => {
  beforeEach(() => {
    vi.stubEnv("AIOS_OIDC_APP_ORIGIN", "");
    vi.stubEnv("NEXT_PUBLIC_APP_ORIGIN", "https://belakb.by");
    vi.stubEnv("NEXT_PUBLIC_KEYCLOAK_ISSUER", "https://auth.belakb.by/realms/aios");
    vi.stubEnv("NEXT_PUBLIC_KEYCLOAK_CLIENT_ID", "aios-backend");
  });
  afterEach(() => vi.unstubAllEnvs());

  it("preserves the production callback when no server override is configured", () => {
    expect(resolveKeycloakConfig("http://127.0.0.1:13101/api/auth/oidc/start")?.redirectUri)
      .toBe("https://belakb.by/api/auth/oidc/callback");
  });

  it("uses one runtime origin for PKCE callback and post-login redirects", () => {
    vi.stubEnv("AIOS_OIDC_APP_ORIGIN", "http://127.0.0.1:3100/");
    expect(resolveKeycloakConfig("http://127.0.0.1:13101/api/auth/oidc/start"))
      .toEqual({ issuer: "https://auth.belakb.by/realms/aios", clientId: "aios-backend",
        redirectUri: "http://127.0.0.1:3100/api/auth/oidc/callback" });
    expect(oidcAppOrigin("http://127.0.0.1:13101/api/auth/oidc/callback"))
      .toBe("http://127.0.0.1:3100");
  });

  it("keeps the request-origin fallback when neither origin is configured", () => {
    vi.stubEnv("NEXT_PUBLIC_APP_ORIGIN", "");
    expect(resolveKeycloakConfig("http://127.0.0.1:3100/api/auth/oidc/start")?.redirectUri)
      .toBe("http://127.0.0.1:3100/api/auth/oidc/callback");
  });

  it.each([
    "https://erp.example.test/path", "https://erp.example.test/?query=1",
    "https://user:pass@erp.example.test", "javascript:alert(1)",
  ])("rejects a server override that is not an HTTP(S) origin: %s", (origin) => {
    vi.stubEnv("AIOS_OIDC_APP_ORIGIN", origin);
    expect(() => resolveKeycloakConfig("http://127.0.0.1:3100/api/auth/oidc/start"))
      .toThrow("Invalid AIOS_OIDC_APP_ORIGIN");
  });
});
