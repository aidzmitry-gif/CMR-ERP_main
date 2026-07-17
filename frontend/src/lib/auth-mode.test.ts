import { describe, expect, it } from "vitest";

import { frontendAuthMode, keycloakPublicConfig } from "@/lib/auth-mode";
import { tokenEndpointIssuer } from "@/lib/keycloak";

describe("frontendAuthMode", () => {
  it("defaults to dev", () => {
    const prev = process.env.NEXT_PUBLIC_AUTH_MODE;
    delete process.env.NEXT_PUBLIC_AUTH_MODE;
    expect(frontendAuthMode()).toBe("dev");
    process.env.NEXT_PUBLIC_AUTH_MODE = prev;
  });

  it("accepts oidc", () => {
    const prev = process.env.NEXT_PUBLIC_AUTH_MODE;
    process.env.NEXT_PUBLIC_AUTH_MODE = "oidc";
    expect(frontendAuthMode()).toBe("oidc");
    process.env.NEXT_PUBLIC_AUTH_MODE = prev;
  });
});

describe("keycloakPublicConfig", () => {
  it("null without issuer/client", () => {
    const a = process.env.NEXT_PUBLIC_KEYCLOAK_ISSUER;
    const b = process.env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID;
    delete process.env.NEXT_PUBLIC_KEYCLOAK_ISSUER;
    delete process.env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID;
    expect(keycloakPublicConfig()).toBeNull();
    process.env.NEXT_PUBLIC_KEYCLOAK_ISSUER = a;
    process.env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID = b;
  });

  it("builds config when set", () => {
    const a = process.env.NEXT_PUBLIC_KEYCLOAK_ISSUER;
    const b = process.env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID;
    const c = process.env.NEXT_PUBLIC_APP_ORIGIN;
    process.env.NEXT_PUBLIC_KEYCLOAK_ISSUER = "https://auth.belakb.by/realms/aios";
    process.env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID = "aios-backend";
    process.env.NEXT_PUBLIC_APP_ORIGIN = "https://belakb.by";
    const cfg = keycloakPublicConfig();
    expect(cfg?.issuer).toBe("https://auth.belakb.by/realms/aios");
    expect(cfg?.clientId).toBe("aios-backend");
    expect(cfg?.redirectUri).toBe("https://belakb.by/api/auth/oidc/callback");
    process.env.NEXT_PUBLIC_KEYCLOAK_ISSUER = a;
    process.env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID = b;
    process.env.NEXT_PUBLIC_APP_ORIGIN = c;
  });
});

describe("tokenEndpointIssuer", () => {
  it("falls back to public issuer", () => {
    const prev = process.env.KEYCLOAK_INTERNAL_ISSUER;
    delete process.env.KEYCLOAK_INTERNAL_ISSUER;
    expect(tokenEndpointIssuer("https://auth.belakb.by/realms/aios/")).toBe(
      "https://auth.belakb.by/realms/aios",
    );
    process.env.KEYCLOAK_INTERNAL_ISSUER = prev;
  });

  it("prefers KEYCLOAK_INTERNAL_ISSUER", () => {
    const prev = process.env.KEYCLOAK_INTERNAL_ISSUER;
    process.env.KEYCLOAK_INTERNAL_ISSUER = "http://127.0.0.1:8080/realms/aios/";
    expect(tokenEndpointIssuer("https://auth.belakb.by/realms/aios")).toBe(
      "http://127.0.0.1:8080/realms/aios",
    );
    process.env.KEYCLOAK_INTERNAL_ISSUER = prev;
  });
});
