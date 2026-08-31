// Silent OIDC refresh on navigations / API when access is near expiry.

import { NextResponse, type NextRequest } from "next/server";

import { ROLE_COOKIE, TOKEN_COOKIE } from "@/lib/access";
import { isOnboardingRole, resolveAppRole } from "@/lib/app-role";
import { keycloakPublicConfig } from "@/lib/auth-mode";
import {
  REFRESH_COOKIE,
  accessTokenNeedsRefresh,
  refreshAccessToken,
  rolesFromAccessToken,
} from "@/lib/keycloak-token";
import { applyOidcTokenCookies } from "@/lib/oidc-cookies";

export async function middleware(req: NextRequest): Promise<NextResponse> {
  const res = NextResponse.next();
  const access = req.cookies.get(TOKEN_COOKIE)?.value;
  const refresh = req.cookies.get(REFRESH_COOKIE)?.value;
  let role = req.cookies.get(ROLE_COOKIE)?.value;
  if (refresh && accessTokenNeedsRefresh(access)) {
    const cfg = keycloakPublicConfig();
    if (cfg) {
      const tokens = await refreshAccessToken({
        issuer: cfg.issuer,
        clientId: cfg.clientId,
        refreshToken: refresh,
      });
      if (tokens?.access_token) {
        applyOidcTokenCookies(tokens, (name, value, opts) => res.cookies.set(name, value, opts));
        role = resolveAppRole(rolesFromAccessToken(tokens.access_token));
      }
    }
  }

  // Не даём приглашённому обойти onboarding прямым URL к CRM/ERP. API защищён
  // backend-RBAC отдельно; этот редирект исключает загрузку data-oriented UI.
  const path = req.nextUrl.pathname;
  if (isOnboardingRole(role) && path !== "/onboarding") {
    return NextResponse.redirect(new URL("/onboarding", req.url));
  }
  if (!isOnboardingRole(role) && path === "/onboarding" && role !== undefined) {
    return NextResponse.redirect(new URL("/", req.url));
  }
  return res;
}

export const config = {
  matcher: [
    /*
     * Page navigations only. `/api/*` refreshes inside the proxy / oidc routes
     * (avoids double refresh-token rotation with middleware).
     */
    "/((?!_next/static|_next/image|favicon.ico|api/).*)",
  ],
};
