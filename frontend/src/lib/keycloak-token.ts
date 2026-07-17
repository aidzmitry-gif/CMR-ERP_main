// Edge-safe Keycloak token helpers (no Node crypto). Used by middleware + route handlers.

export const REFRESH_COOKIE = "aios_refresh_token";

export type OidcTokens = {
  access_token: string;
  refresh_token?: string;
  id_token?: string;
  expires_in?: number;
};

/**
 * Issuer base for server-side token/refresh calls.
 * Prefer KEYCLOAK_INTERNAL_ISSUER when the public hostname hairpins on the box.
 */
export function tokenEndpointIssuer(publicIssuer: string): string {
  const internal = (process.env.KEYCLOAK_INTERNAL_ISSUER ?? "").replace(/\/$/, "");
  return internal || publicIssuer.replace(/\/$/, "");
}

/** Decode JWT payload without verifying (UI / expiry only; backend verifies Bearer). */
export function peekJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const part = token.split(".")[1];
    if (!part) return null;
    const pad = "=".repeat((4 - (part.length % 4)) % 4);
    const b64 = (part + pad).replace(/-/g, "+").replace(/_/g, "/");
    const json =
      typeof atob === "function"
        ? atob(b64)
        : Buffer.from(b64, "base64").toString("utf8");
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/** True when token missing, unreadable, or exp within skewSec (default 60s). */
export function accessTokenNeedsRefresh(
  token: string | undefined | null,
  skewSec = 60,
  nowSec = Math.floor(Date.now() / 1000),
): boolean {
  if (!token) return true;
  const payload = peekJwtPayload(token);
  const exp = payload?.exp;
  if (typeof exp !== "number") return true;
  return exp <= nowSec + skewSec;
}

export async function refreshAccessToken(opts: {
  issuer: string;
  clientId: string;
  refreshToken: string;
}): Promise<OidcTokens | null> {
  const body = new URLSearchParams({
    grant_type: "refresh_token",
    client_id: opts.clientId,
    refresh_token: opts.refreshToken,
  });
  const base = tokenEndpointIssuer(opts.issuer);
  try {
    const res = await fetch(`${base}/protocol/openid-connect/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as OidcTokens;
  } catch {
    return null;
  }
}

export function rolesFromAccessToken(token: string): string[] {
  const payload = peekJwtPayload(token);
  if (!payload) return [];
  const realm = payload.realm_access as { roles?: string[] } | undefined;
  return (realm?.roles ?? []).filter((r) => typeof r === "string");
}

export function displayNameFromAccessToken(token: string): string {
  const payload = peekJwtPayload(token);
  if (!payload) return "oidc-user";
  const name = payload.name ?? payload.preferred_username ?? payload.sub;
  return typeof name === "string" ? name : "oidc-user";
}
