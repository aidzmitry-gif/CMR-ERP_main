// Native form navigation is required: fetch would follow the SSO redirect in the background.

import { cookies } from "next/headers";

import { ROLE_COOKIE, TOKEN_COOKIE, USER_COOKIE } from "@/lib/access";
import { keycloakPublicConfig } from "@/lib/auth-mode";
import { OIDC_STATE_COOKIE, OIDC_VERIFIER_COOKIE, REFRESH_COOKIE } from "@/lib/keycloak";

export async function POST(req: Request): Promise<Response> {
  const jar = await cookies();
  jar.delete(ROLE_COOKIE);
  jar.delete(USER_COOKIE);
  jar.delete(TOKEN_COOKIE);
  jar.delete(REFRESH_COOKIE);
  jar.delete(OIDC_STATE_COOKIE);
  jar.delete(OIDC_VERIFIER_COOKIE);

  const cfg = keycloakPublicConfig();
  const appOrigin = process.env.NEXT_PUBLIC_APP_ORIGIN || new URL(req.url).origin;
  const location = cfg
    ? `${cfg.issuer}/protocol/openid-connect/logout`
    : new URL("/login", appOrigin).toString();
  return new Response(null, {
    status: 303,
    headers: { Location: location, "Cache-Control": "no-store" },
  });
}
