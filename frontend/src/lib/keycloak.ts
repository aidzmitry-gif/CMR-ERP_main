// Keycloak OIDC helpers (PKCE). Used by /api/auth/oidc/* routes.

import { createHash, randomBytes } from "crypto";

import { keycloakPublicConfig } from "@/lib/auth-mode";

export const OIDC_VERIFIER_COOKIE = "aios_oidc_verifier";
export const OIDC_STATE_COOKIE = "aios_oidc_state";
export const REFRESH_COOKIE = "aios_refresh_token";

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

/**
 * Issuer base for server-side token/refresh calls.
 * Prefer KEYCLOAK_INTERNAL_ISSUER (e.g. http://127.0.0.1:8080/realms/aios) when the
 * public hostname hairpins (ECONNREFUSED on the box's own public IP).
 * Browser redirects still use the public NEXT_PUBLIC_KEYCLOAK_ISSUER.
 */
export function tokenEndpointIssuer(publicIssuer: string): string {
  const internal = (process.env.KEYCLOAK_INTERNAL_ISSUER ?? "").replace(/\/$/, "");
  return internal || publicIssuer.replace(/\/$/, "");
}

export async function exchangeCode(opts: {
  issuer: string;
  clientId: string;
  redirectUri: string;
  code: string;
  verifier: string;
}): Promise<{
  access_token: string;
  refresh_token?: string;
  id_token?: string;
  expires_in?: number;
} | null> {
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
    return (await res.json()) as {
      access_token: string;
      refresh_token?: string;
      id_token?: string;
      expires_in?: number;
    };
  } catch {
    return null;
  }
}

/** Decode JWT payload without verifying (roles for UI cookie only; backend verifies Bearer). */
export function peekJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const part = token.split(".")[1];
    if (!part) return null;
    const json = Buffer.from(part, "base64url").toString("utf8");
    return JSON.parse(json) as Record<string, unknown>;
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
