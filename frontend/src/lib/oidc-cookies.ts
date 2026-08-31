// Apply refreshed OIDC cookies (shared by middleware + route handlers). No next/headers.

import { ROLE_COOKIE, TOKEN_COOKIE, USER_COOKIE } from "@/lib/access";
import { resolveAppRole } from "@/lib/app-role";
import {
  REFRESH_COOKIE,
  type OidcTokens,
  displayNameFromAccessToken,
  rolesFromAccessToken,
} from "@/lib/keycloak-token";

const YEAR = 60 * 60 * 24 * 365;

type CookieSetter = (
  name: string,
  value: string,
  opts: { path: string; httpOnly: boolean; sameSite: "lax"; maxAge: number },
) => void;

export function applyOidcTokenCookies(tokens: OidcTokens, set: CookieSetter): void {
  const base = { path: "/", httpOnly: true, sameSite: "lax" as const };
  set(TOKEN_COOKIE, tokens.access_token, { ...base, maxAge: tokens.expires_in ?? 300 });
  if (tokens.refresh_token) {
    set(REFRESH_COOKIE, tokens.refresh_token, { ...base, maxAge: YEAR });
  }
  const roles = rolesFromAccessToken(tokens.access_token);
  const role = resolveAppRole(roles);
  set(ROLE_COOKIE, role, { ...base, maxAge: YEAR });
  set(USER_COOKIE, displayNameFromAccessToken(tokens.access_token), { ...base, maxAge: YEAR });
}
