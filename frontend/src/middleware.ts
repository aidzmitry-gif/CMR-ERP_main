// Silent OIDC refresh on navigations / API when access is near expiry.

import { NextResponse, type NextRequest } from "next/server";

import { TOKEN_COOKIE } from "@/lib/access";
import { keycloakPublicConfig } from "@/lib/auth-mode";
import {
  REFRESH_COOKIE,
  accessTokenNeedsRefresh,
  refreshAccessToken,
} from "@/lib/keycloak-token";
import { applyOidcTokenCookies } from "@/lib/oidc-cookies";

export async function middleware(req: NextRequest): Promise<NextResponse> {
  const res = NextResponse.next();
  const access = req.cookies.get(TOKEN_COOKIE)?.value;
  const refresh = req.cookies.get(REFRESH_COOKIE)?.value;
  if (!refresh || !accessTokenNeedsRefresh(access)) return res;

  const cfg = keycloakPublicConfig();
  if (!cfg) return res;

  const tokens = await refreshAccessToken({
    issuer: cfg.issuer,
    clientId: cfg.clientId,
    refreshToken: refresh,
  });
  if (!tokens?.access_token) return res;

  applyOidcTokenCookies(tokens, (name, value, opts) => res.cookies.set(name, value, opts));
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
