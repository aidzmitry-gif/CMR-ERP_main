// Client-safe auth mode / Keycloak public config (no next/headers).

export type FrontendAuthMode = "dev" | "oidc";

/** Frontend auth mode. Default ``dev`` — picker login; ``oidc`` — Keycloak redirect. */
export function frontendAuthMode(): FrontendAuthMode {
  const raw = (process.env.NEXT_PUBLIC_AUTH_MODE ?? "dev").trim().toLowerCase();
  return raw === "oidc" ? "oidc" : "dev";
}

export interface KeycloakPublicConfig {
  issuer: string;
  clientId: string;
  /** Absolute URL of the OIDC callback route on this frontend. */
  redirectUri: string;
}

/**
 * Public Keycloak settings for browser redirect / PKCE.
 * Empty issuer → SSO button hidden (dev-only login).
 */
export function keycloakPublicConfig(): KeycloakPublicConfig | null {
  const issuer = (process.env.NEXT_PUBLIC_KEYCLOAK_ISSUER ?? "").replace(/\/$/, "");
  const clientId = (process.env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID ?? "").trim();
  const appOrigin = (process.env.NEXT_PUBLIC_APP_ORIGIN ?? "").replace(/\/$/, "");
  if (!issuer || !clientId) return null;
  const redirectUri = appOrigin
    ? `${appOrigin}/api/auth/oidc/callback`
    : ""; // filled at runtime on server from request URL when empty
  return { issuer, clientId, redirectUri };
}
