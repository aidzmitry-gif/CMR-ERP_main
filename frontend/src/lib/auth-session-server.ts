// Server-only (Route Handlers): refresh access cookie via cookies().

import { cookies } from "next/headers";

import { TOKEN_COOKIE } from "@/lib/access";
import { keycloakPublicConfig } from "@/lib/auth-mode";
import {
  REFRESH_COOKIE,
  accessTokenNeedsRefresh,
  refreshAccessToken,
} from "@/lib/keycloak-token";
import { applyOidcTokenCookies } from "@/lib/oidc-cookies";

/** Refresh access cookie when near expiry. Returns usable access token (or null). */
export async function ensureFreshAccessToken(): Promise<string | null> {
  const jar = await cookies();
  const access = jar.get(TOKEN_COOKIE)?.value ?? null;
  const refresh = jar.get(REFRESH_COOKIE)?.value;
  if (!accessTokenNeedsRefresh(access)) return access;
  if (!refresh) return access;

  const cfg = keycloakPublicConfig();
  if (!cfg) return access;

  const tokens = await refreshAccessToken({
    issuer: cfg.issuer,
    clientId: cfg.clientId,
    refreshToken: refresh,
  });
  if (!tokens?.access_token) return access;

  applyOidcTokenCookies(tokens, (name, value, opts) => jar.set(name, value, opts));
  return tokens.access_token;
}
