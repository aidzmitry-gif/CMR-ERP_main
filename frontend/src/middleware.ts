// Silent OIDC refresh on navigations / API when access is near expiry.

import { NextResponse, type NextRequest } from "next/server";

import { ROLE_COOKIE, TOKEN_COOKIE } from "@/lib/access";
import { isOnboardingRole, resolveAppRole } from "@/lib/app-role";
import { frontendAuthMode, keycloakPublicConfig } from "@/lib/auth-mode";
import {
  REFRESH_COOKIE,
  accessTokenNeedsRefresh,
  refreshAccessToken,
  rolesFromAccessToken,
} from "@/lib/keycloak-token";
import { applyOidcTokenCookies } from "@/lib/oidc-cookies";

export async function middleware(req: NextRequest): Promise<NextResponse> {
  let res = NextResponse.next();
  const redirect = (path: string) => {
    const redirected = NextResponse.redirect(new URL(path, req.url));
    // A redirect must also persist rotated refresh/access cookies.
    for (const cookie of res.cookies.getAll()) redirected.cookies.set(cookie);
    return redirected;
  };
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
        // SSR must receive the refreshed token in THIS request. Setting only
        // response cookies leaves the page fetching with an expired token.
        applyOidcTokenCookies(tokens, (name, value) => req.cookies.set(name, value));
        res = NextResponse.next({ request: { headers: req.headers } });
        applyOidcTokenCookies(tokens, (name, value, opts) => res.cookies.set(name, value, opts));
        role = resolveAppRole(rolesFromAccessToken(tokens.access_token));
      }
    }
  }

  // Не даём приглашённому обойти onboarding прямым URL к CRM/ERP. API защищён
  // backend-RBAC отдельно; этот редирект исключает загрузку data-oriented UI.
  const path = req.nextUrl.pathname;
  if (
    frontendAuthMode() === "oidc" &&
    (path.startsWith("/erp") || path.startsWith("/crm") || path === "/onboarding") &&
    accessTokenNeedsRefresh(req.cookies.get(TOKEN_COOKIE)?.value, 0)
  ) {
    return redirect("/login?error=session_expired");
  }
  if (isOnboardingRole(role) && path !== "/onboarding") {
    return redirect("/onboarding");
  }
  if (!isOnboardingRole(role) && path === "/onboarding" && role !== undefined) {
    return redirect("/");
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
