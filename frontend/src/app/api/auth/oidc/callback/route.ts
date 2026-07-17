// Keycloak OIDC callback: exchange code → httpOnly cookies (access + role + display name).

import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

import { DEFAULT_ROLE, ROLE_COOKIE, TOKEN_COOKIE, USER_COOKIE } from "@/lib/access";
import {
  OIDC_STATE_COOKIE,
  OIDC_VERIFIER_COOKIE,
  REFRESH_COOKIE,
  displayNameFromAccessToken,
  exchangeCode,
  resolveKeycloakConfig,
  rolesFromAccessToken,
} from "@/lib/keycloak";

const YEAR = 60 * 60 * 24 * 365;

/** Public site origin for redirects (Caddy→:3100 otherwise becomes localhost). */
function appOrigin(req: NextRequest): string {
  const fromEnv = (process.env.NEXT_PUBLIC_APP_ORIGIN ?? "").replace(/\/$/, "");
  if (fromEnv) return fromEnv;
  return new URL(req.url).origin;
}

function redirectTo(req: NextRequest, path: string): NextResponse {
  return NextResponse.redirect(new URL(path, appOrigin(req)));
}

export async function GET(req: NextRequest): Promise<Response> {
  const url = req.nextUrl;
  const err = url.searchParams.get("error");
  if (err) {
    return redirectTo(req, `/login?error=${encodeURIComponent(err)}`);
  }

  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  if (!code || !state) {
    return redirectTo(req, "/login?error=missing_code");
  }

  const cfg = resolveKeycloakConfig(req.url);
  if (!cfg) {
    return redirectTo(req, "/login?error=kc_unconfigured");
  }

  const jar = await cookies();
  const expectState = jar.get(OIDC_STATE_COOKIE)?.value;
  const verifier = jar.get(OIDC_VERIFIER_COOKIE)?.value;
  jar.delete(OIDC_STATE_COOKIE);
  jar.delete(OIDC_VERIFIER_COOKIE);

  if (!expectState || !verifier || expectState !== state) {
    return redirectTo(req, "/login?error=state_mismatch");
  }

  const tokens = await exchangeCode({
    issuer: cfg.issuer,
    clientId: cfg.clientId,
    redirectUri: cfg.redirectUri,
    code,
    verifier,
  });
  if (!tokens?.access_token) {
    return redirectTo(req, "/login?error=token_exchange");
  }

  const roles = rolesFromAccessToken(tokens.access_token);
  const role = roles.includes("director")
    ? "director"
    : roles[0] && !roles[0].startsWith("default-") && roles[0] !== "offline_access"
      ? roles[0]
      : DEFAULT_ROLE;
  const display = displayNameFromAccessToken(tokens.access_token);

  const opts = { path: "/", httpOnly: true, sameSite: "lax" as const, maxAge: YEAR };
  jar.set(TOKEN_COOKIE, tokens.access_token, {
    ...opts,
    maxAge: tokens.expires_in ?? 300,
  });
  if (tokens.refresh_token) {
    jar.set(REFRESH_COOKIE, tokens.refresh_token, opts);
  }
  jar.set(ROLE_COOKIE, role, opts);
  // Next cookies().set already encodes; do not encodeURIComponent (else %2520).
  jar.set(USER_COOKIE, display, opts);

  return redirectTo(req, "/crm/deals");
}
