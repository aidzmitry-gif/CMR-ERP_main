// Re-export token helpers + PKCE (Node crypto) for route handlers.

import { createHash, randomBytes } from "crypto";

import { keycloakPublicConfig } from "@/lib/auth-mode";
import {
  type OidcTokens,
  REFRESH_COOKIE,
  accessTokenNeedsRefresh,
  displayNameFromAccessToken,
  peekJwtPayload,
  refreshAccessToken,
  rolesFromAccessToken,
  tokenEndpointIssuer,
} from "@/lib/keycloak-token";

export {
  REFRESH_COOKIE,
  accessTokenNeedsRefresh,
  displayNameFromAccessToken,
  peekJwtPayload,
  refreshAccessToken,
  rolesFromAccessToken,
  tokenEndpointIssuer,
};
export type { OidcTokens };

export const OIDC_VERIFIER_COOKIE = "aios_oidc_verifier";
export const OIDC_STATE_COOKIE = "aios_oidc_state";

export function randomUrlSafe(bytes = 32): string {
  return randomBytes(bytes).toString("base64url");
}

export function pkceChallenge(verifier: string): string {
  return createHash("sha256").update(verifier).digest("base64url");
}

export function resolveKeycloakConfig(requestUrl: string): {
  issuer: string;
  clientId: string;
  redirectUri: string;
} | null {
  const base = keycloakPublicConfig();
  if (!base) return null;
  if (base.redirectUri) return base;
  const origin = new URL(requestUrl).origin;
  return { ...base, redirectUri: `${origin}/api/auth/oidc/callback` };
}

export function authorizeUrl(opts: {
  issuer: string;
  clientId: string;
  redirectUri: string;
  state: string;
  challenge: string;
}): string {
  const u = new URL(`${opts.issuer}/protocol/openid-connect/auth`);
  u.searchParams.set("client_id", opts.clientId);
  u.searchParams.set("redirect_uri", opts.redirectUri);
  u.searchParams.set("response_type", "code");
  u.searchParams.set("scope", "openid profile");
  u.searchParams.set("state", opts.state);
  u.searchParams.set("code_challenge", opts.challenge);
  u.searchParams.set("code_challenge_method", "S256");
  return u.toString();
}

export async function exchangeCode(opts: {
  issuer: string;
  clientId: string;
  redirectUri: string;
  code: string;
  verifier: string;
}): Promise<OidcTokens | null> {
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: opts.clientId,
    code: opts.code,
    redirect_uri: opts.redirectUri,
    code_verifier: opts.verifier,
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
